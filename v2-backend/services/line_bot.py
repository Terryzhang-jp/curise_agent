"""
LINE Bot service layer — user mapping, session management, agent invocation, message delivery.

Uses the same ReAct agent infrastructure as the web chat (routes/chat.py).
Supports: DM, group chat (@mention only), text messages, image messages.
"""

import logging
import os
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session as DBSession

from config import settings
from database import SessionLocal
from models import AgentSession, LineUser, User

logger = logging.getLogger(__name__)

RESET_KEYWORDS = {"新对话", "reset", "重置", "新建对话"}
PROCESSING_TIMEOUT_MINUTES = 5
UPLOAD_DIR = settings.UPLOAD_DIR

# ─── LINE Messaging API ─────────────────────────────────────

def _get_messaging_api():
    """Create a LINE MessagingApi client."""
    from linebot.v3.messaging import Configuration, ApiClient, MessagingApi

    config = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
    client = ApiClient(config)
    return MessagingApi(client)


def _get_messaging_api_blob():
    """Create a LINE MessagingApiBlob client for binary content (images, etc.)."""
    from linebot.v3.messaging import Configuration, ApiClient, MessagingApiBlob

    config = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
    client = ApiClient(config)
    return MessagingApiBlob(client)


def _split_message(text: str, max_len: int = 5000) -> list[str]:
    """Split text into chunks that fit LINE's 5000-char limit.

    Strategy: split by double-newline → single-newline → hard-cut.
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Try to split at a double newline
        cut = remaining[:max_len].rfind("\n\n")
        if cut > max_len // 2:
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip("\n")
            continue

        # Try single newline
        cut = remaining[:max_len].rfind("\n")
        if cut > max_len // 2:
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip("\n")
            continue

        # Hard cut
        chunks.append(remaining[:max_len])
        remaining = remaining[max_len:]

    return [c for c in chunks if c.strip()]


def deliver_message(reply_token: str, target_id: str, text: str, received_at: float):
    """Deliver message — Reply API if within 25s, else Push API.

    target_id can be a user_id (DM) or group_id (group chat).
    """
    from linebot.v3.messaging import (
        TextMessage, ReplyMessageRequest, PushMessageRequest,
    )

    api = _get_messaging_api()
    chunks = _split_message(text)
    # LINE allows max 5 messages per request
    batches = [chunks[i:i + 5] for i in range(0, len(chunks), 5)]

    elapsed = time.time() - received_at

    for batch_idx, batch in enumerate(batches):
        messages = [TextMessage(text=c) for c in batch]

        # First batch within 25s → try Reply API (free)
        if batch_idx == 0 and elapsed < 25:
            try:
                api.reply_message(ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=messages,
                ))
                logger.info("LINE reply sent (%d chars, %.1fs)", sum(len(c) for c in batch), elapsed)
                continue
            except Exception as e:
                logger.warning("Reply API failed (%.1fs elapsed), falling back to Push: %s", elapsed, e)

        # Fallback: Push API
        try:
            api.push_message(PushMessageRequest(
                to=target_id,
                messages=messages,
            ))
            logger.info("LINE push sent to %s (%d chars)", target_id, sum(len(c) for c in batch))
        except Exception as e:
            logger.error("Push API failed for %s: %s", target_id, e)


def _push_message(target_id: str, text: str):
    """Send a push message (for follow/join events)."""
    from linebot.v3.messaging import TextMessage, PushMessageRequest

    api = _get_messaging_api()
    try:
        api.push_message(PushMessageRequest(
            to=target_id,
            messages=[TextMessage(text=text)],
        ))
    except Exception as e:
        logger.error("Push message failed for %s: %s", target_id, e)


# ─── Image Download ──────────────────────────────────────────

def _download_image(message_id: str) -> bytes | None:
    """Download image content from LINE servers via MessagingApiBlob."""
    try:
        blob_api = _get_messaging_api_blob()
        content = blob_api.get_message_content(message_id)
        logger.info("Downloaded image %s (%d bytes)", message_id, len(content))
        return bytes(content)
    except Exception as e:
        logger.error("Failed to download image %s: %s", message_id, e)
        return None


# ─── Source Helpers ───────────────────────────────────────────

def _is_group_source(event) -> bool:
    """Check if event comes from a group chat."""
    from linebot.v3.webhooks import GroupSource
    return isinstance(event.source, GroupSource)


def _get_reply_target_id(event) -> str:
    """Get the target ID for push messages — group_id for groups, user_id for DMs."""
    if _is_group_source(event):
        return event.source.group_id
    return event.source.user_id


def _is_bot_mentioned(event) -> bool:
    """Check if the bot was @mentioned in a text message."""
    mention = getattr(event.message, "mention", None)
    if not mention:
        return False
    for mentionee in (mention.mentionees or []):
        if getattr(mentionee, "is_self", False):
            return True
    return False


def _strip_mention(text: str, event) -> str:
    """Remove the @bot mention from text so the agent gets clean input."""
    mention = getattr(event.message, "mention", None)
    if not mention:
        return text
    # Remove mention spans in reverse order (so indices stay valid)
    spans = []
    for m in (mention.mentionees or []):
        if getattr(m, "is_self", False):
            spans.append((m.index, m.index + m.length))
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + text[end:]
    return text.strip()


# ─── User Mapping ────────────────────────────────────────────

def _get_line_profile(line_user_id: str) -> str | None:
    """Fetch LINE display name via Profile API."""
    try:
        api = _get_messaging_api()
        profile = api.get_profile(line_user_id)
        return profile.display_name
    except Exception as e:
        logger.warning("Could not fetch LINE profile for %s: %s", line_user_id, e)
        return None


def _get_or_create_line_user(db: DBSession, line_user_id: str) -> LineUser:
    """Look up or auto-register a LINE user.

    On first contact:
      1. Fetch display name from LINE Profile API
      2. Create a system User record (email=line_{id}@line.bot, role=employee)
      3. Create a LineUser record linking the two
    """
    from security import hash_password

    line_user = db.query(LineUser).filter(LineUser.line_user_id == line_user_id).first()

    if line_user:
        line_user.last_active_at = datetime.utcnow()
        db.commit()
        return line_user

    # First time — auto-register
    display_name = _get_line_profile(line_user_id) or f"LINE User {line_user_id[:8]}"

    # Create system user
    email = f"line_{line_user_id}@line.bot"
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        user_id = existing_user.id
    else:
        new_user = User(
            email=email,
            hashed_password=hash_password(str(uuid.uuid4())),  # random unusable password
            full_name=display_name,
            role="employee",
            is_active=True,
        )
        db.add(new_user)
        db.flush()
        user_id = new_user.id

    line_user = LineUser(
        line_user_id=line_user_id,
        user_id=user_id,
        display_name=display_name,
    )
    db.add(line_user)
    db.commit()
    db.refresh(line_user)
    logger.info("Registered LINE user: %s → user_id=%d", display_name, user_id)
    return line_user


# ─── Session Management ──────────────────────────────────────

def _get_or_create_session(db: DBSession, line_user: LineUser, force_new: bool = False) -> AgentSession:
    """Get the active session for a LINE user, or create a new one.

    If force_new is True, always creates a new session.
    """
    if not force_new and line_user.active_session_id:
        session = db.query(AgentSession).filter(
            AgentSession.id == line_user.active_session_id,
        ).first()
        if session and session.status in ("active", "processing"):
            return session

    # Create new session
    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=line_user.user_id,
        title="LINE 对话",
        status="active",
    )
    db.add(session)
    line_user.active_session_id = session.id
    db.commit()
    db.refresh(session)
    logger.info("Created new session %s for LINE user %s", session.id, line_user.line_user_id)
    return session


# ─── Agent Invocation ────────────────────────────────────────

def _run_agent_for_line(session_id: str, user_message: str, db: DBSession, file_bytes: bytes | None = None) -> str:
    """Run the ReAct chat agent and return the final answer text.

    Reuses _create_chat_agent from routes/chat.py — same LLM, tools, skills.
    """
    from routes.chat import _create_chat_agent

    agent = _create_chat_agent(session_id, db, file_bytes=file_bytes)
    result = agent.run(user_message)
    return result or "（Agent 未返回内容）"


# ─── Core Message Processing ─────────────────────────────────

def _process_message(event, received_at: float, user_text: str, file_bytes: bytes | None = None):
    """Shared logic for text and image messages.

    Flow: resolve user → manage session → run agent → deliver reply.
    """
    line_user_id = event.source.user_id
    reply_token = event.reply_token
    target_id = _get_reply_target_id(event)

    db = SessionLocal()
    try:
        # Resolve user
        line_user = _get_or_create_line_user(db, line_user_id)

        if line_user.is_blocked:
            return

        # Check reset keyword
        force_new = user_text.lower() in RESET_KEYWORDS or user_text in RESET_KEYWORDS
        if force_new:
            _get_or_create_session(db, line_user, force_new=True)
            deliver_message(reply_token, target_id, "已创建新对话，请发送您的问题。", received_at)
            return

        # Get or create session
        session = _get_or_create_session(db, line_user)

        # Concurrency guard: if agent is already processing, reject
        if session.status == "processing":
            # Check for stale processing (>5 min)
            if session.updated_at and (datetime.utcnow() - session.updated_at) > timedelta(minutes=PROCESSING_TIMEOUT_MINUTES):
                session.status = "active"
                db.commit()
                logger.warning("Recovered stale processing session %s", session.id)
            else:
                deliver_message(reply_token, target_id, "正在处理上一条消息，请稍候再试。", received_at)
                return

        # Mark session as processing
        session.status = "processing"
        session.updated_at = datetime.utcnow()

        # Auto-set title from first message
        from models import AgentMessage
        msg_count = db.query(AgentMessage).filter(
            AgentMessage.session_id == session.id,
            AgentMessage.role == "user",
        ).count()
        if msg_count == 0:
            title = user_text[:50]
            if len(user_text) > 50:
                title += "..."
            session.title = title

        db.commit()

        # Run agent
        try:
            answer = _run_agent_for_line(session.id, user_text, db, file_bytes=file_bytes)
        except Exception as e:
            logger.error("Agent error for session %s: %s", session.id, e, exc_info=True)
            answer = f"抱歉，处理您的消息时出错了: {str(e)}"
        finally:
            # Reset session status
            session = db.query(AgentSession).filter(AgentSession.id == session.id).first()
            if session:
                session.status = "active"
                session.updated_at = datetime.utcnow()
                db.commit()

        # Deliver reply
        deliver_message(reply_token, target_id, answer, received_at)

    except Exception as e:
        logger.error("_process_message error for %s: %s", line_user_id, e, exc_info=True)
    finally:
        db.close()


# ─── Event Handlers ──────────────────────────────────────────

def handle_text_message(event, received_at: float):
    """Handle a text message from LINE (DM or group).

    In group chats, only responds when @mentioned.
    """
    is_group = _is_group_source(event)

    # In groups, only respond when bot is @mentioned
    if is_group and not _is_bot_mentioned(event):
        return

    user_text = event.message.text.strip()

    # Strip @mention from text for cleaner agent input
    if is_group:
        user_text = _strip_mention(user_text, event)
        if not user_text:
            return

    _process_message(event, received_at, user_text)


def handle_image_message(event, received_at: float):
    """Handle an image message — download and pass to agent."""
    target_id = _get_reply_target_id(event)

    # In groups, ignore images (no way to @mention with an image easily)
    if _is_group_source(event):
        return

    # Download image from LINE
    message_id = event.message.id
    file_bytes = _download_image(message_id)

    if not file_bytes:
        deliver_message(event.reply_token, target_id, "图片下载失败，请重试。", received_at)
        return

    # Save to uploads/ for agent access
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:8]}_line_image.jpg"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(file_bytes)
    logger.info("Saved LINE image to %s (%d bytes)", filepath, len(file_bytes))

    # Pass to agent with a prompt
    user_text = "用户上传了一张图片，请分析图片内容。"
    _process_message(event, received_at, user_text, file_bytes=file_bytes)


def handle_follow_event(event):
    """Handle follow (subscribe) event — welcome message + auto-register."""
    line_user_id = event.source.user_id

    db = SessionLocal()
    try:
        _get_or_create_line_user(db, line_user_id)
        _push_message(line_user_id,
            "欢迎使用邮轮供应链管理助手！\n\n"
            "您可以直接发送消息查询产品、订单、供应商等信息。\n"
            "也可以发送图片让 AI 分析内容。\n\n"
            "发送「新对话」可以开始新的对话。"
        )
    except Exception as e:
        logger.error("handle_follow_event error for %s: %s", line_user_id, e, exc_info=True)
    finally:
        db.close()


def handle_join_event(event):
    """Handle bot joining a group — send welcome message."""
    group_id = event.source.group_id

    _push_message(group_id,
        "大家好！我是邮轮供应链管理助手。\n\n"
        "在群里 @我 并发送问题即可使用。\n"
        "例如：@助手 查一下所有供应商\n\n"
        "私聊我可以直接发消息，无需 @。"
    )
    logger.info("Bot joined group %s", group_id)


def handle_non_text_message(event, received_at: float):
    """Handle unsupported message types (sticker, video, etc.)."""
    # In groups, silently ignore
    if _is_group_source(event):
        return

    target_id = _get_reply_target_id(event)
    deliver_message(
        event.reply_token,
        target_id,
        "暂时只支持文字和图片消息，请发送文字或图片。",
        received_at,
    )

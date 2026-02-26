"""
LINE Webhook route — receives events from LINE Platform, dispatches to handlers.

Authentication: LINE signature verification (not JWT).
Processing: immediate 200 response, agent runs in background threads.
"""

import logging
import threading
import time

from fastapi import APIRouter, Request, HTTPException

from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/line", tags=["line"])


def _get_parser():
    """Create LINE WebhookParser (lazy, so import only when needed)."""
    from linebot.v3.webhook import WebhookParser

    return WebhookParser(settings.LINE_CHANNEL_SECRET)


@router.post("/webhook")
async def webhook(request: Request):
    """LINE Webhook endpoint.

    1. Verify X-Line-Signature
    2. Parse events
    3. Dispatch each event to a background thread
    4. Return 200 immediately (LINE requires response within a few seconds)
    """
    if not settings.LINE_CHANNEL_SECRET or not settings.LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(500, "LINE Bot not configured")

    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    # Parse + verify signature
    from linebot.v3.webhook import InvalidSignatureError
    parser = _get_parser()
    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        logger.warning("Invalid LINE signature")
        raise HTTPException(400, "Invalid signature")

    received_at = time.time()

    from linebot.v3.webhooks import (
        MessageEvent, FollowEvent, JoinEvent,
        TextMessageContent, ImageMessageContent,
    )
    from services.line_bot import (
        handle_text_message, handle_image_message,
        handle_follow_event, handle_join_event, handle_non_text_message,
    )

    for event in events:
        if isinstance(event, MessageEvent):
            if isinstance(event.message, TextMessageContent):
                threading.Thread(
                    target=handle_text_message,
                    args=(event, received_at),
                    daemon=True,
                ).start()
            elif isinstance(event.message, ImageMessageContent):
                threading.Thread(
                    target=handle_image_message,
                    args=(event, received_at),
                    daemon=True,
                ).start()
            else:
                threading.Thread(
                    target=handle_non_text_message,
                    args=(event, received_at),
                    daemon=True,
                ).start()
        elif isinstance(event, FollowEvent):
            threading.Thread(
                target=handle_follow_event,
                args=(event,),
                daemon=True,
            ).start()
        elif isinstance(event, JoinEvent):
            threading.Thread(
                target=handle_join_event,
                args=(event,),
                daemon=True,
            ).start()

    return "OK"

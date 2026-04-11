"""
Workspace State Middleware — DeerFlow UploadsMiddleware pattern.

Scans the agent's workspace directory before every LLM call and injects
a summary of available files. This ensures the agent always knows what
files it has generated, even after context compression wipes message history.

Key design decisions:
  - Uses filesystem as ground truth (not message history)
  - Only injects when workspace has files (no context cost when empty)
  - Transient injection into history (removed after LLM call by engine)
  - General-purpose: works for any tool that writes to workspace
    (inquiry generation, bash scripts, data exports, etc.)

Inspired by:
  - DeerFlow UploadsMiddleware (filesystem scan + re-injection)
  - DeerFlow TodoMiddleware (state re-injection after summarization)
  - Anthropic "lightweight identifiers" pattern
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from services.agent.hooks import Middleware

logger = logging.getLogger(__name__)

# Only show files modified within this window (seconds)
# Prevents stale files from previous sessions from cluttering context
RECENCY_WINDOW = 3600  # 1 hour


class WorkspaceStateMiddleware(Middleware):
    """Inject workspace file listing before every LLM call.

    Requires ctx to have:
      - ctx.workspace_dir: str (session workspace path)
    """

    def __init__(self):
        self._last_injection: str | None = None  # Track to avoid duplicate injection

    def before_agent(self, user_message: str, ctx: Any) -> str:
        """Store workspace scan result on ctx for engine to inject transiently."""
        parts = []

        # 1. Scan workspace files (if workspace exists)
        workspace = getattr(ctx, 'workspace_dir', None)
        if workspace and os.path.isdir(workspace):
            try:
                files = self._scan_workspace(workspace)
                if files:
                    parts.append(self._format_file_list(files))
            except Exception as e:
                logger.debug("WorkspaceState scan failed: %s", e)

        # 2. Read structured session state from DB (Cloud Run compatible)
        # (Anthropic "structured note-taking" pattern)
        try:
            db = getattr(ctx, 'db', None)
            session_id = getattr(ctx, 'session_id', None) or getattr(ctx, 'pipeline_session_id', None)
            if db and session_id:
                from core.models import AgentSession
                session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
                if session and session.context_data:
                    op_state = session.context_data.get("operation_state")
                    if op_state and isinstance(op_state, dict):
                        parts.append("[上次操作上下文]")
                        for key, val in op_state.items():
                            parts.append(f"  {key}: {val}")
        except Exception as e:
            logger.debug("Session state read failed: %s", e)

        ctx._workspace_file_summary = "\n".join(parts) if parts else ""
        return user_message

    @staticmethod
    def _scan_workspace(workspace_dir: str) -> list[dict]:
        """Scan workspace directory for recent files."""
        now = time.time()
        files = []

        try:
            for entry in os.scandir(workspace_dir):
                if not entry.is_file():
                    continue
                stat = entry.stat()
                age = now - stat.st_mtime
                if age > RECENCY_WINDOW:
                    continue  # Skip old files

                size_kb = stat.st_size / 1024
                ext = os.path.splitext(entry.name)[1].lower()

                files.append({
                    "name": entry.name,
                    "size_kb": round(size_kb, 1),
                    "age_seconds": round(age),
                    "ext": ext,
                })
        except OSError:
            pass

        # Sort by modification time (newest first)
        files.sort(key=lambda f: f["age_seconds"])
        return files[:10]  # Cap at 10 files to limit context

    @staticmethod
    def _format_file_list(files: list[dict]) -> str:
        """Format file list as a concise system injection."""
        lines = ["[工作目录文件]"]

        for f in files:
            age = f["age_seconds"]
            if age < 60:
                time_str = f"{age}秒前"
            elif age < 3600:
                time_str = f"{age // 60}分钟前"
            else:
                time_str = f"{age // 3600}小时前"

            lines.append(f"  - {f['name']} ({f['size_kb']}KB, {time_str})")

        lines.append("")
        lines.append("这些文件在工作目录中，可直接用 bash + Python 读取或修改。")

        return "\n".join(lines)

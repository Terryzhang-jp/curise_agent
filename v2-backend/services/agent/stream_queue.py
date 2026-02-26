"""
Thread-safe per-session event queue registry.

Used to bridge the agent background thread (producer) with the async SSE
endpoint (consumer).  Each active session gets its own ``queue.Queue``.
"""

from __future__ import annotations

import threading
from queue import Queue
from typing import Any

_lock = threading.Lock()
_queues: dict[str, Queue] = {}


def get_or_create_queue(session_id: str) -> Queue:
    with _lock:
        if session_id not in _queues:
            _queues[session_id] = Queue()
        return _queues[session_id]


def get_queue(session_id: str) -> Queue | None:
    with _lock:
        return _queues.get(session_id)


def remove_queue(session_id: str) -> None:
    with _lock:
        _queues.pop(session_id, None)


def push_event(session_id: str, event: dict[str, Any]) -> None:
    """Push an event to the session's queue (no-op if no queue exists)."""
    q = get_queue(session_id)
    if q is not None:
        q.put(event)

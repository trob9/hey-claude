"""
session.py - Conversation session state management.

After Claude responds, we stay "in session" for a configurable timeout window.
Any speech during that window is sent to Claude as a follow-up using --resume,
which tells Claude Code CLI to continue the same conversation thread.

When the timeout expires (user stopped talking), the session_id is cleared
and the next interaction requires the wake phrase again.

This is why you don't need to say "hey claude" for every message in a conversation.
"""

from __future__ import annotations

import time


class Session:
    """
    Tracks the active conversation session with Claude Code.

    session_id is the value returned by Claude Code CLI's `--output-format stream-json`
    result event. Passing it to `--resume <session_id>` on the next invocation
    continues the conversation with full history.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        """
        Args:
            timeout: Seconds of inactivity before session expires.
                     After this, next utterance requires the wake phrase.
        """
        self.timeout = timeout
        self._session_id: str | None = None
        self._last_activity: float | None = None

    @property
    def session_id(self) -> str | None:
        """Current session ID, or None if no active session."""
        return self._session_id if self.is_active() else None

    def is_active(self) -> bool:
        """True if we're within the timeout window of the last interaction."""
        if self._session_id is None or self._last_activity is None:
            return False
        return time.monotonic() - self._last_activity < self.timeout

    def time_remaining(self) -> float:
        """Seconds until session expires. 0 if already expired."""
        if not self.is_active():
            return 0.0
        elapsed = time.monotonic() - self._last_activity
        return max(0.0, self.timeout - elapsed)

    def update(self, session_id: str) -> None:
        """
        Called after each successful Claude response to refresh the session.

        Args:
            session_id: The session_id from the Claude Code CLI result event.
        """
        self._session_id = session_id
        self._last_activity = time.monotonic()

    def touch(self) -> None:
        """Reset the inactivity timer without changing the session_id."""
        if self._session_id is not None:
            self._last_activity = time.monotonic()

    def clear(self) -> None:
        """Explicitly end the session (e.g. on 'goodbye' command)."""
        self._session_id = None
        self._last_activity = None

    def __repr__(self) -> str:
        if self.is_active():
            return f"Session(id={self._session_id[:8]}..., remaining={self.time_remaining():.1f}s)"
        return "Session(inactive)"

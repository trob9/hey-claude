"""
session.py - Conversation session state management.

After Claude responds, we stay "in session" for a configurable timeout window.
Any speech during that window is sent to Claude as a follow-up using --resume,
which tells Claude Code CLI to continue the same conversation thread.

When the timeout expires (user stopped talking), the session_id is cleared
and the next interaction requires the wake phrase again.

We also maintain a local history buffer (last N exchanges). This is injected
into each prompt so that even if --resume fails and CC starts a fresh session,
Claude still has the conversation context it needs to continue naturally.
"""

from __future__ import annotations

import time


# Max number of past exchanges (user + assistant pairs) to keep in memory.
# 4 pairs = last 4 back-and-forth turns. Keeps prompts short.
MAX_HISTORY = 4


class Session:
    """
    Tracks the active conversation session with Claude Code.

    Two mechanisms for continuity:
    1. --resume <session_id>: Claude Code's built-in session resumption.
    2. History injection: We maintain a local log of recent turns and
       prepend them to each prompt as a fallback when --resume is ignored.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._session_id: str | None = None
        self._last_activity: float | None = None
        # Each entry: {"user": "...", "assistant": "..."}
        self._history: list[dict[str, str]] = []

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
        Refresh the session after a Claude response.

        We only update the session_id if:
        - There was no previous session (first turn), OR
        - The returned ID matches what we passed in (resume actually worked).

        This prevents us from chasing a newly-minted empty session when
        Claude Code silently ignores --resume and starts fresh.
        """
        if self._session_id is None:
            # First turn — always accept the returned session_id
            self._session_id = session_id
        elif session_id != self._session_id:
            # CC returned a different ID — it started a new session.
            # Keep our original ID so next turn still attempts --resume
            # with the session that actually has history server-side.
            print(
                f"[SESSION] CC returned new session ({session_id[:8]}...) — "
                f"keeping original ({self._session_id[:8]}...) for --resume",
                flush=True,
            )
        else:
            # Same ID — resume is working, update normally
            self._session_id = session_id

        self._last_activity = time.monotonic()

    def add_history(self, user_text: str, assistant_text: str) -> None:
        """Record a completed exchange for history injection."""
        self._history.append({
            "user": user_text[:300],           # cap length
            "assistant": assistant_text[:300],
        })
        # Keep only the most recent N exchanges
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

    def history_prompt(self) -> str:
        """
        Format recent history as a preamble for the next prompt.

        Returns empty string if no history yet (first turn).
        Injected into every prompt so CC has context even if --resume fails.
        """
        if not self._history:
            return ""
        lines = ["[Conversation so far this session:]"]
        for turn in self._history:
            lines.append(f"User: {turn['user']}")
            lines.append(f"You: {turn['assistant']}")
        lines.append("[End of history — continue from here]")
        return "\n".join(lines)

    def touch(self) -> None:
        """Reset the inactivity timer without changing session state."""
        if self._session_id is not None:
            self._last_activity = time.monotonic()

    def clear(self) -> None:
        """Explicitly end the session and wipe history."""
        self._session_id = None
        self._last_activity = None
        self._history = []

    def __repr__(self) -> str:
        if self.is_active():
            return (
                f"Session(id={self._session_id[:8]}..., "
                f"remaining={self.time_remaining():.1f}s, "
                f"history={len(self._history)} turns)"
            )
        return "Session(inactive)"

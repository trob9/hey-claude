"""Tests for Session state management."""

import time
import pytest
from hey_claude.session import Session


def test_new_session_is_inactive():
    s = Session(timeout=5.0)
    assert not s.is_active()
    assert s.session_id is None


def test_session_becomes_active_on_update():
    s = Session(timeout=5.0)
    s.update("abc-123")
    assert s.is_active()
    assert s.session_id == "abc-123"


def test_session_expires_after_timeout():
    s = Session(timeout=0.1)
    s.update("abc-123")
    time.sleep(0.15)
    assert not s.is_active()
    assert s.session_id is None


def test_session_id_hidden_when_expired():
    s = Session(timeout=0.05)
    s.update("my-session")
    time.sleep(0.1)
    # session_id property returns None when expired
    assert s.session_id is None


def test_clear_ends_session():
    s = Session(timeout=30.0)
    s.update("active-session")
    assert s.is_active()
    s.clear()
    assert not s.is_active()
    assert s.session_id is None


def test_touch_resets_timer():
    s = Session(timeout=0.2)
    s.update("test-id")
    time.sleep(0.15)
    s.touch()  # Reset without changing session_id
    time.sleep(0.1)
    # Should still be active (timer was reset)
    assert s.is_active()


def test_time_remaining_decreases():
    s = Session(timeout=10.0)
    s.update("id")
    r1 = s.time_remaining()
    time.sleep(0.05)
    r2 = s.time_remaining()
    assert r2 < r1


def test_time_remaining_zero_when_inactive():
    s = Session(timeout=5.0)
    assert s.time_remaining() == 0.0


def test_update_keeps_original_when_cc_returns_different_id():
    """If CC ignores --resume and returns a new session_id, we keep the original."""
    s = Session(timeout=30.0)
    s.update("original-session")
    s.update("fresh-session-from-cc")  # CC started fresh — should keep "original"
    assert s.session_id == "original-session"

def test_update_accepts_same_id():
    s = Session(timeout=30.0)
    s.update("my-session")
    s.update("my-session")  # Same ID — resume worked fine
    assert s.session_id == "my-session"


def test_repr():
    s = Session(timeout=30.0)
    assert "inactive" in repr(s)
    s.update("abc-123-def-456")
    assert "abc-123" in repr(s)


class TestHistory:
    def test_history_empty_on_new_session(self):
        s = Session(timeout=30.0)
        assert s.history_prompt() == ""

    def test_history_prompt_contains_exchanges(self):
        s = Session(timeout=30.0)
        s.add_history("list my files", "You have three files on your desktop.")
        prompt = s.history_prompt()
        assert "list my files" in prompt
        assert "three files" in prompt

    def test_history_capped_at_max(self):
        from hey_claude.session import MAX_HISTORY
        s = Session(timeout=30.0)
        for i in range(MAX_HISTORY + 3):
            s.add_history(f"user turn {i}", f"assistant turn {i}")
        # Only MAX_HISTORY most recent turns kept
        prompt = s.history_prompt()
        assert f"user turn {MAX_HISTORY + 2}" in prompt   # most recent kept
        assert "user turn 0" not in prompt                # oldest dropped

    def test_clear_wipes_history(self):
        s = Session(timeout=30.0)
        s.update("some-id")
        s.add_history("hello", "world")
        s.clear()
        assert s.history_prompt() == ""

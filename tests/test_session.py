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


def test_update_changes_session_id():
    s = Session(timeout=30.0)
    s.update("first")
    s.update("second")
    assert s.session_id == "second"


def test_repr():
    s = Session(timeout=30.0)
    assert "inactive" in repr(s)
    s.update("abc-123-def-456")
    assert "abc-123" in repr(s)

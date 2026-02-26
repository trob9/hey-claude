"""Tests for STT helper logic (no actual model calls)."""

import pytest
from hey_claude.stt import STT


@pytest.fixture
def stt():
    # We test the helper methods only - no model loading required
    return STT()


class TestContainsWakePhrase:
    def test_exact_match(self, stt):
        assert stt.contains_wake_phrase("hey claude what's up") is True

    def test_not_present(self, stt):
        assert stt.contains_wake_phrase("what's the weather today") is False

    def test_common_mishearing_hey_cloud(self, stt):
        assert stt.contains_wake_phrase("hey cloud what time is it") is True

    def test_case_insensitive(self, stt):
        assert stt.contains_wake_phrase("HEY CLAUDE help me") is True

    def test_empty_string(self, stt):
        assert stt.contains_wake_phrase("") is False

    def test_just_wake_phrase(self, stt):
        assert stt.contains_wake_phrase("hey claude") is True

    def test_hay_claude_variant(self, stt):
        assert stt.contains_wake_phrase("hay claude check this") is True


class TestStripWakePhrase:
    def test_strips_hey_claude(self, stt):
        result = stt.strip_wake_phrase("hey claude list my files")
        assert result == "list my files"

    def test_strips_hey_cloud_variant(self, stt):
        result = stt.strip_wake_phrase("hey cloud what time is it")
        assert result == "what time is it"

    def test_strips_leading_punctuation(self, stt):
        result = stt.strip_wake_phrase("hey claude, open the file")
        assert result == "open the file"

    def test_returns_original_if_no_wake_phrase(self, stt):
        result = stt.strip_wake_phrase("what is the weather")
        assert result == "what is the weather"

    def test_just_wake_phrase_returns_empty(self, stt):
        result = stt.strip_wake_phrase("hey claude")
        assert result == ""

    def test_case_insensitive_strip(self, stt):
        result = stt.strip_wake_phrase("HEY CLAUDE run the tests")
        assert result == "run the tests"

"""Tests for runner.py parsing logic (no actual Claude calls)."""

import pytest
from hey_claude.runner import extract_tags, strip_tags, _extract_speak, _format_tool_input


class TestExtractTags:
    def test_extracts_single_tag(self):
        text = "Some text <STATUS>reading the file</STATUS> more text"
        assert extract_tags(text, "STATUS") == ["reading the file"]

    def test_extracts_multiple_tags(self):
        text = "<STATUS>checking</STATUS> ... <STATUS>done</STATUS>"
        assert extract_tags(text, "STATUS") == ["checking", "done"]

    def test_extracts_speak_tag(self):
        text = "reasoning text\n<SPEAK>Here's your answer.</SPEAK>"
        assert extract_tags(text, "SPEAK") == ["Here's your answer."]

    def test_returns_empty_list_when_no_match(self):
        assert extract_tags("no tags here", "SPEAK") == []

    def test_case_insensitive(self):
        text = "<speak>Hello</speak>"
        assert extract_tags(text, "SPEAK") == ["Hello"]

    def test_multiline_content(self):
        text = "<SPEAK>Line one.\nLine two.</SPEAK>"
        result = extract_tags(text, "SPEAK")
        assert len(result) == 1
        assert "Line one." in result[0]


class TestExtractSpeak:
    def test_extracts_speak_tag(self):
        text = "<STATUS>running</STATUS>\nsome reasoning\n<SPEAK>All done!</SPEAK>"
        assert _extract_speak(text) == "All done!"

    def test_falls_back_to_cleaned_text(self):
        text = "I ran the command and it worked."
        result = _extract_speak(text)
        assert "I ran" in result

    def test_returns_done_for_empty_text(self):
        assert _extract_speak("") == "Done."
        assert _extract_speak(None) == "Done."

    def test_truncates_very_long_fallback(self):
        long_text = "word " * 200
        result = _extract_speak(long_text)
        assert len(result) <= 403  # 400 chars + "..."

    def test_strips_status_tags_from_fallback(self):
        text = "<STATUS>checking</STATUS>\nThe answer is 42."
        result = _extract_speak(text)
        # Should not include STATUS tag content in fallback
        assert "checking" not in result or "42" in result

    def test_multiple_speak_tags_joined(self):
        text = "<SPEAK>First part.</SPEAK> ... <SPEAK>Second part.</SPEAK>"
        result = _extract_speak(text)
        assert "First part" in result
        assert "Second part" in result


class TestFormatToolInput:
    def test_bash_command(self):
        result = _format_tool_input("Bash", {"command": "ls -la"})
        assert "ls -la" in result

    def test_bash_truncates_long_command(self):
        long_cmd = "echo " + "x" * 200
        result = _format_tool_input("Bash", {"command": long_cmd})
        assert len(result) <= 123  # 120 + "..."

    def test_read_shows_path(self):
        result = _format_tool_input("Read", {"file_path": "/Users/tom/file.go"})
        assert "/Users/tom/file.go" in result

    def test_grep_shows_pattern(self):
        result = _format_tool_input("Grep", {"pattern": "func main"})
        assert "func main" in result

    def test_unknown_tool_dumps_json(self):
        result = _format_tool_input("UnknownTool", {"key": "value"})
        assert "value" in result


class TestStripTags:
    def test_removes_speak_tag(self):
        text = "text <SPEAK>spoken part</SPEAK> more"
        result = strip_tags(text)
        assert "<SPEAK>" not in result
        assert "spoken part" not in result

    def test_preserves_non_tag_text(self):
        text = "hello world"
        assert strip_tags(text) == "hello world"

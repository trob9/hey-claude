"""
runner.py - Runs Claude Code CLI as a subprocess and streams its output.

Claude Code CLI flags we use:
  -p / --print                     Non-interactive mode (one-shot)
  --dangerously-skip-permissions   Auto-approve ALL tool calls (Bash, Read, Write, etc.)
  --output-format stream-json      Emit newline-delimited JSON events as they happen
  --include-partial-messages       Stream text/tool deltas in real-time
  --append-system-prompt           Add our voice instructions on top of CC's default prompt
  --resume <session_id>            Continue a previous conversation thread

The stream-json format emits events like:
  {"type": "system",    "subtype": "init", "session_id": "...", "tools": [...]}
  {"type": "assistant", "message": {"content": [{"type":"text","text":"..."}, ...]}}
  {"type": "assistant", "message": {"content": [{"type":"tool_use","name":"Bash","input":{...}}]}}
  {"type": "user",      "message": {"content": [{"type":"tool_result","content":"..."}]}}
  {"type": "result",    "subtype": "success", "session_id": "...", "result": "..."}

We parse these events to:
1. Extract <STATUS>...</STATUS> tags from text blocks → speak immediately
2. Print tool calls and results to terminal
3. Extract <SPEAK>...</SPEAK> from the final result → speak as the response
4. Return the new session_id for conversation continuity
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional


CLAUDE_BINARY = "/usr/local/bin/claude"


def extract_tags(text: str, tag: str) -> list[str]:
    """Extract all occurrences of <tag>content</tag> from text."""
    pattern = rf"<{tag}>(.*?)</{tag}>"
    return re.findall(pattern, text, re.IGNORECASE | re.DOTALL)


def strip_tags(text: str) -> str:
    """Remove all XML-style tags and their content from text."""
    return re.sub(r"<[^>]+>.*?</[^>]+>", "", text, flags=re.DOTALL).strip()


def run_claude(
    prompt: str,
    system_prompt: str,
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    on_status: Optional[Callable[[str], None]] = None,
    on_tool_call: Optional[Callable[[str, dict], None]] = None,
    on_tool_result: Optional[Callable[[str, bool], None]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Run Claude Code CLI with the given prompt and stream its output.

    Args:
        prompt:        The user's request (transcribed speech).
        system_prompt: Appended system prompt (voice instructions).
        session_id:    If set, resume this conversation thread (--resume).
        cwd:           Working directory for Claude. Defaults to user home.
        on_status:     Called with STATUS tag content as they appear (for TTS).
        on_tool_call:  Called with (tool_name, input_dict) when a tool is invoked.
        on_tool_result: Called with (preview, is_error) after a tool completes.

    Returns:
        (new_session_id, speak_text) tuple.
        new_session_id: Save this to resume the conversation next turn.
        speak_text: The extracted <SPEAK>...</SPEAK> content, or fallback text.
    """
    resolved_cwd = str(Path(cwd or "~").expanduser()) if cwd else str(Path.home())

    # Build the CLI command
    cmd = [
        CLAUDE_BINARY,
        "-p", prompt,
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",                       # Required when using stream-json + --print
        "--include-partial-messages",
        "--append-system-prompt", system_prompt,
    ]

    if session_id:
        cmd += ["--resume", session_id]

    # Inherit the full environment so Vertex AI vars pass through
    env = os.environ.copy()

    print(f"\n[YOU] {prompt}", flush=True)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=resolved_cwd,
            env=env,
        )
    except FileNotFoundError:
        print(f"[ERROR] Claude binary not found at {CLAUDE_BINARY}", file=sys.stderr)
        return None, "I couldn't start Claude Code. Check that it's installed."

    new_session_id: Optional[str] = None
    final_result_text: Optional[str] = None
    spoken_statuses: set[str] = set()  # deduplicate STATUS calls

    # Accumulators for partial streaming
    current_text_block = ""
    current_tool_name: Optional[str] = None
    current_tool_input_json = ""

    try:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON output (e.g. debug lines) - print and continue
                print(f"[CC] {line}", flush=True)
                continue

            event_type = event.get("type", "")

            # ── System init ──────────────────────────────────────────────────
            if event_type == "system" and event.get("subtype") == "init":
                sid = event.get("session_id", "")
                tools = event.get("tools", [])
                print(f"[INIT] session={sid[:12]}... tools={len(tools)}", flush=True)

            # ── Assistant message (complete or partial) ───────────────────────
            elif event_type == "assistant":
                content = event.get("message", {}).get("content", [])
                for block in content:
                    block_type = block.get("type", "")

                    if block_type == "text":
                        text = block.get("text", "")
                        current_text_block += text

                        # Extract any STATUS tags that have fully arrived
                        statuses = extract_tags(current_text_block, "STATUS")
                        for status in statuses:
                            status = status.strip()
                            if status and status not in spoken_statuses:
                                spoken_statuses.add(status)
                                print(f"[STATUS] {status}", flush=True)
                                if on_status:
                                    on_status(status)

                    elif block_type == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_input = block.get("input", {})
                        current_tool_name = tool_name

                        # Pretty-print tool call to terminal
                        input_preview = _format_tool_input(tool_name, tool_input)
                        print(f"[TOOL] {tool_name}: {input_preview}", flush=True)

                        if on_tool_call:
                            on_tool_call(tool_name, tool_input)

            # ── User message (contains tool results) ─────────────────────────
            elif event_type == "user":
                content = event.get("message", {}).get("content", [])
                for block in content:
                    if block.get("type") == "tool_result":
                        result_content = block.get("content", "")
                        is_error = block.get("is_error", False)

                        # Normalise result to string
                        if isinstance(result_content, list):
                            result_str = "\n".join(
                                b.get("text", "") for b in result_content
                                if isinstance(b, dict)
                            )
                        else:
                            result_str = str(result_content)

                        preview = result_str[:200].replace("\n", " ")
                        suffix = "..." if len(result_str) > 200 else ""
                        status = "ERR" if is_error else "OK"
                        print(f"[RESULT:{status}] {preview}{suffix}", flush=True)

                        if on_tool_result:
                            on_tool_result(preview, is_error)

            # ── Stream events (partial deltas) ────────────────────────────────
            elif event_type == "stream_event":
                # These are the real-time deltas. We use the higher-level
                # assistant/user message events for our main parsing above.
                # But we watch for text_delta to stream STATUS tags early.
                sub = event.get("event", {})
                delta = sub.get("delta", {})
                if delta.get("type") == "text_delta":
                    partial = delta.get("text", "")
                    current_text_block += partial

            # ── Final result ──────────────────────────────────────────────────
            elif event_type == "result":
                new_session_id = event.get("session_id")
                subtype = event.get("subtype", "")

                if subtype == "success":
                    final_result_text = event.get("result", "")
                elif subtype == "error_max_turns":
                    final_result_text = "I hit the turn limit on that task."
                    print(f"[WARN] Max turns reached", flush=True)
                elif subtype in ("error", "error_during_execution"):
                    err = event.get("error", event.get("result", "Unknown error"))
                    final_result_text = f"Something went wrong: {err}"
                    print(f"[ERROR] {err}", flush=True)

    finally:
        proc.wait()
        stderr_output = proc.stderr.read() if proc.stderr else ""
        if stderr_output.strip():
            # Only print stderr if it looks like an actual error, not progress noise
            if any(w in stderr_output.lower() for w in ["error", "failed", "exception"]):
                print(f"[CC STDERR] {stderr_output[:500]}", file=sys.stderr, flush=True)

    # Extract the spoken response from <SPEAK>...</SPEAK> in the final result
    speak_text = _extract_speak(final_result_text or current_text_block)

    return new_session_id, speak_text


def _extract_speak(text: str) -> Optional[str]:
    """
    Pull out <SPEAK>...</SPEAK> content from the response.

    Falls back gracefully if Claude didn't follow the format:
    - If there's a SPEAK tag, use it.
    - If there's no SPEAK tag but there's text after stripping STATUS/tool tags, use that.
    - If nothing, return a generic "done" message.
    """
    if not text:
        return "Done."

    speaks = extract_tags(text, "SPEAK")
    if speaks:
        return " ".join(s.strip() for s in speaks if s.strip())

    # Claude didn't use a SPEAK tag - strip other tags and use the remaining text
    cleaned = re.sub(r"<[A-Z_]+>.*?</[A-Z_]+>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip()

    if cleaned:
        # Truncate if very long (voice shouldn't read a 500-word essay)
        if len(cleaned) > 400:
            cleaned = cleaned[:397] + "..."
        return cleaned

    return "Done."


def _format_tool_input(tool_name: str, tool_input: dict) -> str:
    """Format tool input for readable terminal display."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return cmd[:120] + ("..." if len(cmd) > 120 else "")
    elif tool_name in ("Read", "Write", "Edit"):
        path = tool_input.get("file_path", tool_input.get("path", "?"))
        return str(path)
    elif tool_name in ("Grep",):
        pattern = tool_input.get("pattern", "?")
        return f'"{pattern}"'
    else:
        # Generic: dump first 120 chars of JSON
        raw = json.dumps(tool_input)
        return raw[:120] + ("..." if len(raw) > 120 else "")

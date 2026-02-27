"""
fast_runner.py - Direct Vertex AI API call for baby claude mode.

Bypasses Claude Code CLI entirely. No subprocess, no tool loading.
Uses the anthropic[vertex] SDK with streaming so TTS starts on the
first complete sentence rather than waiting for the full response.

Trade-off vs run_claude():
  + No subprocess spawn overhead
  + Streaming → first sentence spoken ~1.5s earlier
  + Short max_tokens keeps responses snappy
  - No tools (no bash, no file access) — baby claude is conversational only
"""

from __future__ import annotations

import os
import re
import sys
from typing import Callable, Optional

from anthropic import AnthropicVertex


# Sentence boundary: ends with . ! ? followed by space or end of string
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')


def _split_sentences(text: str) -> tuple[list[str], str]:
    """
    Split text into complete sentences and a leftover fragment.

    Returns (complete_sentences, remainder).
    """
    parts = _SENTENCE_END.split(text)
    if len(parts) <= 1:
        return [], text
    # Last part is an incomplete sentence (or empty)
    return parts[:-1], parts[-1]


def run_baby_claude(
    prompt: str,
    system_prompt: str,
    on_sentence: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """
    Call Claude Haiku directly via Vertex AI SDK with streaming.

    As each complete sentence arrives it's passed to on_sentence()
    for immediate TTS — the user starts hearing the answer before
    the full response is generated.

    Args:
        prompt:       The user's request.
        system_prompt: Voice assistant instructions.
        on_sentence:  Called with each complete sentence as it streams in.
                      Use this to pipe to macOS say immediately.

    Returns:
        The full response text, or None on error.
    """
    project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
    region = os.environ.get("CLOUD_ML_REGION", "us-east5")
    model = os.environ.get("BABY_CLAUDE_MODEL", "claude-haiku-4-5")

    if not project_id:
        print("[BABY] ANTHROPIC_VERTEX_PROJECT_ID not set", file=sys.stderr)
        return None

    try:
        client = AnthropicVertex(project_id=project_id, region=region)
    except Exception as e:
        print(f"[BABY] Failed to create Vertex client: {e}", file=sys.stderr)
        return None

    print(f"\n[YOU] {prompt}", flush=True)
    print(f"[BABY] → {model} via Vertex (streaming)", flush=True)

    accumulated = ""
    buffer = ""
    sentences_spoken: list[str] = []

    try:
        with client.messages.stream(
            model=model,
            max_tokens=300,      # Baby claude answers are short
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                accumulated += chunk
                buffer += chunk

                # Fire on_sentence for each complete sentence as it arrives
                if on_sentence:
                    complete, buffer = _split_sentences(buffer)
                    for sentence in complete:
                        sentence = sentence.strip()
                        if sentence:
                            print(f"[SPEAK:BABY] {sentence}", flush=True)
                            on_sentence(sentence)
                            sentences_spoken.append(sentence)

        # Speak any remaining buffer after stream ends
        if on_sentence and buffer.strip():
            sentence = buffer.strip()
            print(f"[SPEAK:BABY] {sentence}", flush=True)
            on_sentence(sentence)
            sentences_spoken.append(sentence)

    except Exception as e:
        print(f"[BABY] Error: {e}", file=sys.stderr)
        return None

    return accumulated or None

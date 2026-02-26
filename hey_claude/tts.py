"""
tts.py - Text-to-speech via macOS `say` command.

The `say` command is built into macOS and requires no API keys.
We wrap it to support voice selection, rate control, and blocking vs non-blocking.
"""

import subprocess
import shutil
from typing import Optional


def say(
    text: str,
    voice: str = "Samantha",
    rate: Optional[int] = None,
    block: bool = True,
) -> None:
    """
    Speak text using macOS `say`.

    Args:
        text:  Text to speak.
        voice: macOS voice name (Samantha, Alex, Daniel, Karen, etc.)
        rate:  Words per minute. None = system default (~200 wpm).
        block: If True, wait for speech to finish before returning.
               If False, speak in background while code continues.
    """
    if not text or not text.strip():
        return

    if not shutil.which("say"):
        # Graceful fallback on non-macOS systems
        print(f"[TTS] {text}")
        return

    cmd = ["say", "-v", voice]
    if rate is not None:
        cmd += ["-r", str(rate)]
    cmd.append(text.strip())

    if block:
        subprocess.run(cmd, check=False, capture_output=True)
    else:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def list_voices() -> list[str]:
    """Return available macOS voices."""
    result = subprocess.run(
        ["say", "-v", "?"],
        capture_output=True,
        text=True,
        check=False,
    )
    voices = []
    for line in result.stdout.splitlines():
        if line.strip():
            voices.append(line.split()[0])
    return voices

"""
main.py - hey-claude entry point.

Runs the voice assistant loop:
  IDLE mode:    listen for "hey claude" wake phrase
  SESSION mode: accept follow-up commands for 30s without wake phrase

Usage:
    ./venv/bin/python3 main.py
    ./venv/bin/python3 main.py --cwd /path/to/work/dir
    ./venv/bin/python3 main.py --voice Alex --rate 175
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

import yaml

# Local modules
from hey_claude.audio import AudioCapture
from hey_claude.runner import run_claude
from hey_claude.fast_runner import run_baby_claude
from hey_claude.session import Session
from hey_claude.stt import STT
from hey_claude.tts import say


# ─────────────────────────────────────────────────────────────────────────────
# Config loading
# ─────────────────────────────────────────────────────────────────────────────

def load_config(config_path: str = "config.yaml") -> dict:
    path = Path(config_path)
    if not path.exists():
        # Try relative to script directory
        path = Path(__file__).parent / config_path
    if not path.exists():
        print(f"[WARN] config.yaml not found, using defaults")
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_system_prompt(prompt_path: str = "prompts/system.md") -> str:
    path = Path(prompt_path)
    if not path.exists():
        path = Path(__file__).parent / prompt_path
    if not path.exists():
        print(f"[WARN] system prompt not found at {prompt_path}, using minimal default")
        return (
            "You are a voice assistant. Wrap your final spoken response in "
            "<SPEAK>...</SPEAK> tags. Use <STATUS>brief phrase</STATUS> before "
            "each tool call. Be concise - responses are spoken aloud."
        )
    return path.read_text().strip()


# ─────────────────────────────────────────────────────────────────────────────
# Signal handling
# ─────────────────────────────────────────────────────────────────────────────

_running = True

def _signal_handler(sig, frame):
    global _running
    print("\n\n[hey-claude] Shutting down...", flush=True)
    _running = False

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global _running

    parser = argparse.ArgumentParser(description="hey-claude voice assistant")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--cwd", default=None, help="Working directory for Claude")
    parser.add_argument("--voice", default=None, help="macOS voice (e.g. Samantha, Alex)")
    parser.add_argument("--rate", type=int, default=None, help="TTS words per minute")
    parser.add_argument("--model", default=None, help="Claude model override (e.g. claude-haiku-4-5)")
    args = parser.parse_args()

    # Load config
    cfg = load_config(args.config)
    audio_cfg = cfg.get("audio", {})
    stt_cfg = cfg.get("stt", {})
    session_cfg = cfg.get("session", {})
    tts_cfg = cfg.get("tts", {})
    claude_cfg = cfg.get("claude", {})
    wake_cfg = cfg.get("wake_word", {})

    # CLI args override config
    voice = args.voice or tts_cfg.get("voice", "Samantha")
    rate = args.rate or tts_cfg.get("rate", 185)
    cwd = args.cwd or claude_cfg.get("cwd", "~")
    wake_phrase = wake_cfg.get("phrase", "hey claude")
    session_timeout = float(session_cfg.get("timeout", 30))

    # Baby Claude settings
    baby_cfg = cfg.get("baby_claude", {})
    baby_model = baby_cfg.get("model", "claude-haiku-4-5")
    baby_voice = baby_cfg.get("voice", "Junior")
    baby_rate = int(baby_cfg.get("rate", 200))

    # Convenience wrapper for TTS — mode="baby" uses high-pitched Junior voice
    def speak(text: str, rate: int = rate, mode: str = "normal", block: bool = True):
        v = baby_voice if mode == "baby" else voice
        r = baby_rate if mode == "baby" else rate
        say(text, voice=v, rate=r, block=block)

    # Load system prompts
    system_prompt = load_system_prompt()
    baby_system_prompt = load_system_prompt("prompts/system_baby.md")

    # Build context line to append to each prompt (tells Claude where it's running)
    def build_context() -> str:
        resolved_cwd = str(Path(cwd).expanduser())
        return f"\n\n[Context: working directory is {resolved_cwd}]"

    # Initialise components
    print("Initialising audio capture...", flush=True)
    audio = AudioCapture(
        sample_rate=audio_cfg.get("sample_rate", 16000),
        silence_duration=audio_cfg.get("silence_threshold", 1.5),
        max_duration=audio_cfg.get("max_recording_duration", 30),
        energy_threshold=audio_cfg.get("energy_threshold", 0.01),
    )

    print("Loading Whisper models (may download on first run)...", flush=True)
    stt = STT(
        wake_model=stt_cfg.get("wake_model", "tiny"),
        command_model=stt_cfg.get("command_model", "small"),
        language=stt_cfg.get("language", "en"),
    )
    stt.preload()  # Load both models into memory now to avoid first-utterance lag

    session = Session(timeout=session_timeout)

    # Track the mode ("normal" or "baby") for the current session so follow-up
    # turns stay in the same mode without needing another wake phrase.
    current_mode = "normal"
    current_model = args.model or None

    print("\n" + "═" * 60)
    print("  hey-claude is ready")
    print(f"  '{wake_phrase}' → Sonnet (normal voice)")
    print(f"  'hey baby claude' → Haiku (high-pitched voice)")
    print(f"  Ctrl+C to quit")
    print("═" * 60 + "\n", flush=True)

    # ── Main loop ─────────────────────────────────────────────────────────────
    while _running:
        try:
            in_session = session.is_active()

            if in_session:
                # ── SESSION MODE ──────────────────────────────────────────────
                # We're in an active conversation. Wait for voice activity.
                # If nothing in timeout window, drop back to idle.
                remaining = session.time_remaining()
                print(
                    f"[SESSION] Listening for follow-up ({remaining:.0f}s remaining)...",
                    flush=True,
                )

                # Single stream: wait for speech AND record it in one call.
                # This avoids the gap between wait_for_activity() closing its stream
                # and capture_until_silence() opening a new one (which clips speech onset).
                audio_data = audio.capture_until_silence(max_duration=min(remaining, session_timeout))

                if not session.is_active():
                    print("[SESSION] Timed out, returning to wake word mode", flush=True)
                    session.clear()
                    current_mode = "normal"
                    current_model = args.model or None
                    print(f"\nSay '{wake_phrase}' to start a new conversation\n", flush=True)
                    continue

                if audio_data is None:
                    # No speech detected before timeout
                    if not session.is_active():
                        session.clear()
                        print(f"\nSay '{wake_phrase}' to start a new conversation\n", flush=True)
                    continue
                transcript = stt.transcribe(audio_data, model="command")
                if not transcript.strip():
                    continue

                # Inject history so CC has context even if --resume fails
                history = session.history_prompt()
                prompt = (history + "\n\n" if history else "") + transcript + build_context()

            else:
                # ── IDLE MODE ─────────────────────────────────────────────────
                audio_data = audio.capture_until_silence()
                if audio_data is None:
                    continue

                quick_transcript = stt.transcribe(audio_data, model="wake")

                # Check baby wake phrase FIRST (it contains "hey claude" as substring)
                if stt.contains_baby_wake_phrase(quick_transcript):
                    current_mode = "baby"
                    current_model = baby_model
                    print(f"[WAKE:BABY] Detected: '{quick_transcript}'", flush=True)
                    command_part = stt.strip_baby_wake_phrase(quick_transcript)
                    # Non-blocking: feedback plays while mic is already open for the command
                    speak("yeah?", mode="baby", block=False)
                elif stt.contains_wake_phrase(quick_transcript, wake_phrase):
                    current_mode = "normal"
                    current_model = args.model or None
                    print(f"[WAKE] Detected: '{quick_transcript}'", flush=True)
                    command_part = stt.strip_wake_phrase(quick_transcript, wake_phrase)
                    speak("mmhm")
                else:
                    continue

                if not command_part:
                    print("[IDLE] Wake phrase only, waiting for command...", flush=True)
                    audio_data = audio.capture_until_silence()
                    if audio_data is None:
                        continue
                    command_part = stt.transcribe(audio_data, model="command")

                if not command_part.strip():
                    speak("I didn't catch that, try again.", mode=current_mode)
                    continue

                prompt = command_part + build_context()

            # ── Goodbye check (anywhere in the flow) ─────────────────────────
            raw_command = prompt.split("[Context:")[0].strip()
            if any(w in raw_command.lower() for w in ["goodbye", "stop listening", "exit", "quit"]):
                session.clear()
                current_mode = "normal"
                current_model = args.model or None
                speak("Goodbye!")
                print("\nSession ended.\n", flush=True)
                continue

            # ── Send to Claude ────────────────────────────────────────────────
            print(f"[PROMPT] {prompt[:120]}", flush=True)

            def on_status(status_text: str):
                speak(status_text, rate=rate + 20)  # Slightly faster for status updates

            if current_mode == "baby":
                # ── Baby claude: direct SDK streaming, no tools, fast ─────────
                full_text = run_baby_claude(
                    prompt=prompt,
                    system_prompt=baby_system_prompt,
                    on_sentence=lambda s: speak(s, mode="baby"),
                )
                speak_text = full_text or "Done."
                # Baby claude sessions don't resume via CC — use touch to keep window open
                session.touch()
                if not session.is_active():
                    # First baby turn: give it a session ID placeholder so is_active() works
                    session._session_id = "baby-session"
                    session._last_activity = __import__("time").monotonic()
            else:
                # ── Normal claude: Claude Code CLI, full tools ────────────────
                new_session_id, speak_text = run_claude(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    session_id=session.session_id,
                    cwd=cwd,
                    model=current_model,
                    on_status=on_status,
                )
                if new_session_id:
                    session.update(new_session_id)
                    print(f"[SESSION] Active (ID: {new_session_id[:12]}...)", flush=True)
                else:
                    session.touch()

                # Speak the response (CLI mode — already spoken via on_status for STATUS tags)
                if speak_text and speak_text != "Done.":
                    raw_user = prompt.split("[End of history")[- 1].split("[Context:")[0].strip()
                    session.add_history(raw_user, speak_text)

                if speak_text:
                    speak(speak_text, mode=current_mode)
                    print(f"[SPEAK:NORMAL] {speak_text}", flush=True)
                else:
                    speak("Done.")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr, flush=True)
            try:
                speak("Something went wrong. Try again.")
            except Exception:
                pass
            time.sleep(1)

    print("\n[hey-claude] Bye!\n")


if __name__ == "__main__":
    main()

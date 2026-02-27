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

    # Convenience wrapper for TTS
    def speak(text: str, rate: int = rate):
        say(text, voice=voice, rate=rate)

    # Load system prompt
    system_prompt = load_system_prompt()

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

    print("\n" + "═" * 60)
    print("  hey-claude is ready")
    print(f"  Say '{wake_phrase}' to start")
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

                activity = audio.wait_for_activity(timeout=min(remaining, session_timeout))

                if not activity or not session.is_active():
                    print("[SESSION] Timed out, returning to wake word mode", flush=True)
                    session.clear()
                    print(f"\nSay '{wake_phrase}' to start a new conversation\n", flush=True)
                    continue

                # Record the follow-up command
                audio_data = audio.capture_until_silence()
                if audio_data is None:
                    continue

                transcript = stt.transcribe(audio_data, model="command")
                if not transcript.strip():
                    continue

                # Allow "goodbye", "stop", "exit" to end the session
                if any(w in transcript.lower() for w in ["goodbye", "stop listening", "exit", "quit"]):
                    session.clear()
                    speak("Goodbye!")
                    print("\nSession ended.\n", flush=True)
                    continue

                # Inject history so CC has context even if --resume fails
                history = session.history_prompt()
                prompt = (history + "\n\n" if history else "") + transcript + build_context()

            else:
                # ── IDLE MODE ─────────────────────────────────────────────────
                # Listen for the wake phrase. Record a short chunk, transcribe
                # with the tiny model, check for "hey claude".

                audio_data = audio.capture_until_silence()
                if audio_data is None:
                    continue

                # Quick transcription with tiny model
                quick_transcript = stt.transcribe(audio_data, model="wake")

                if not stt.contains_wake_phrase(quick_transcript, wake_phrase):
                    # Not a wake phrase - ignore
                    continue

                # Wake phrase detected!
                print(f"[WAKE] Detected: '{quick_transcript}'", flush=True)

                # Audio acknowledgement
                speak("How can I help?", rate=200)

                # Strip the wake phrase - is there a command in the same utterance?
                command_part = stt.strip_wake_phrase(quick_transcript, wake_phrase)

                if not command_part:
                    # Wake phrase only - wait for the actual command
                    print("[IDLE] Wake phrase detected, waiting for command...", flush=True)
                    audio_data = audio.capture_until_silence()
                    if audio_data is None:
                        continue
                    # Transcribe the command with the better model
                    command_part = stt.transcribe(audio_data, model="command")

                if not command_part.strip():
                    speak("I didn't catch that, try again.")
                    continue

                prompt = command_part + build_context()

            # ── Send to Claude ────────────────────────────────────────────────
            # (no history injection on first turn — session is fresh)
            print(f"[PROMPT] {prompt[:120]}", flush=True)

            def on_status(status_text: str):
                speak(status_text, rate=rate + 20)  # Slightly faster for status updates

            new_session_id, speak_text = run_claude(
                prompt=prompt,
                system_prompt=system_prompt,
                session_id=session.session_id,
                cwd=cwd,
                on_status=on_status,
            )

            # Update session for conversation continuity
            if new_session_id:
                session.update(new_session_id)
                print(f"[SESSION] Active (ID: {new_session_id[:12]}...)", flush=True)
            else:
                session.touch()

            # Record this exchange in local history (fallback if --resume fails)
            if speak_text and speak_text != "Done.":
                # Use the raw transcript as the user turn (strip injected history/context)
                raw_user = prompt.split("[End of history")[- 1].split("[Context:")[0].strip()
                session.add_history(raw_user, speak_text)

            # Speak the final response
            if speak_text:
                speak(speak_text)
                print(f"[SPEAK] {speak_text}", flush=True)
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

# CLAUDE.md — hey-claude

## Project Overview

Voice assistant powered by Claude Code. Say "hey claude", speak your request, and Claude executes it with full access to filesystem, terminal, and all Claude Code tools, then speaks the result back.

**Tech:** Python, openai-whisper (local STT), Claude Code CLI, macOS `say` (TTS)
**Repo:** `git@github.com:trob9/hey-claude.git`
**Runs on:** MacBook (not deployed on mini-pc / server)
**Not a web service** — local dev tool, no Docker, no webhook deployment.

---

## How It Works

```
"hey claude list my desktop files"
    ↓ Whisper (local, small model) — wake word detection
    ↓ Whisper (local, small model) — full command transcription
    ↓ Claude Code CLI subprocess (--allowedTools explicit list, stream-json)
    ↓ Bash: ls ~/Desktop
    ↓ macOS say: "You've got six things on your desktop..."
```

- **Wake word:** "hey claude" (fuzzy matching enabled)
- **STT:** openai-whisper running locally (small model, ~461MB, downloaded from Azure CDN on first run)
- **Claude:** Claude Code CLI via subprocess with stream-json output
- **Auth:** Vertex AI via gcloud ADC (`CLAUDE_CODE_USE_VERTEX=1` from shell env)
- **TTS:** macOS `say` — offline, zero setup
- **Session:** 30-second context window between turns

---

## Setup / Running

```bash
cd hey-claude
./setup.sh     # installs Python venv, downloads Whisper models (~500MB first run)

./venv/bin/python3 main.py
# Optional flags:
./venv/bin/python3 main.py --cwd ~/Projects/my-project   # set Claude working dir
./venv/bin/python3 main.py --voice Alex --rate 175        # different voice/speed
```

---

## File Map

| File/Dir | Purpose |
|----------|---------|
| `main.py` | Entry point — wake word loop, session management |
| `hey_claude/audio.py` | Audio capture and VAD (voice activity detection) |
| `hey_claude/stt.py` | Whisper STT wrapper (wake word + command models) |
| `hey_claude/runner.py` | Claude Code CLI subprocess runner (stream-json) |
| `hey_claude/fast_runner.py` | Faster runner variant |
| `hey_claude/session.py` | Session context (30s timeout between turns) |
| `hey_claude/tts.py` | macOS `say` TTS wrapper |
| `config.yaml` | All tunable parameters (see below) |
| `prompts/` | System prompt files for Claude |
| `requirements.txt` | Python dependencies |
| `setup.sh` | One-time setup script |
| `tests/` | Test files |

---

## Configuration (`config.yaml`)

Key settings:

| Setting | Default | Purpose |
|---------|---------|---------|
| `wake_word.phrase` | "hey claude" | Wake phrase |
| `wake_word.fuzzy_match` | true | Allow minor transcription errors |
| `stt.wake_model` | "small" | Whisper model for wake detection |
| `stt.command_model` | "small" | Whisper model for full commands |
| `session.timeout` | 30s | How long before returning to wake mode |
| `audio.silence_threshold` | 1.5s | Silence duration to end recording |
| `tts.voice` | "Samantha" | macOS voice |
| `tts.rate` | 185 | Words per minute |
| `baby_claude.wake_phrase` | "hey baby claude" | Alternate wake for haiku model |
| `claude.max_turns` | 50 | Max tool-call turns per request |

---

## Wake Variants

| Wake phrase | Model | Voice |
|-------------|-------|-------|
| "hey claude" | Claude Code (full) | Samantha |
| "hey baby claude" | claude-haiku-4-5 (faster/cheaper) | Junior (high-pitched) |

---

## Key Constraints

- **This is a local macOS tool** — runs on MacBook, not on the mini-pc. Don't Dockerize or deploy.
- **Requires gcloud ADC** for Vertex AI auth (`gcloud auth application-default login`). `CLAUDE_CODE_USE_VERTEX=1` must be set in shell environment.
- **Whisper models are downloaded on first run** (~500MB). Do not commit them — they're large binaries.
- **Python venv is local** (`./venv/`) — not committed to git.
- **`say` is macOS-only.** TTS will not work on Linux/Windows without modifying `hey_claude/tts.py`.
- **Claude Code CLI must be in PATH** as `claude`.

---

## Logs

Prints to stdout while running:
```
[YOU] list the files here
[INIT] session=abc123... tools=36
[STATUS] listing directory files
[TOOL] Bash: ls /path/to/dir
[CLAUDE] Here are the files: ...
```

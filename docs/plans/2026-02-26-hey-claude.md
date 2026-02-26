# hey-claude Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Voice assistant that wakes on "hey claude", transcribes speech locally (mlx-whisper on M4 Neural Engine), drives Claude Code CLI (full tool set, no approval prompts, Vertex AI auth), speaks back via macOS `say`, and maintains conversation session for 30s after each response.

**Architecture:** Python audio pipeline (sounddevice + webrtcvad + mlx-whisper) feeds transcribed text to Claude Code CLI subprocess (`/usr/local/bin/claude -p ... --dangerously-skip-permissions --output-format stream-json`). Stream-json events are parsed in real-time for terminal display and `<STATUS>`/`<SPEAK>` tag extraction. Session continuity via `--resume <session_id>` across voice turns.

**Tech Stack:** Python 3.12, mlx-whisper (Apple Neural Engine), sounddevice, webrtcvad, pyyaml, Claude Code CLI via subprocess, macOS `say`

---

### Task 1: Project skeleton + git

**Files:**
- Create: `hey_claude/__init__.py`
- Create: `.gitignore`
- Create: `config.yaml`
- Create: `.env.example`

### Task 2: System prompt

**Files:**
- Create: `prompts/system.md`

### Task 3: requirements.txt + setup.sh

**Files:**
- Create: `requirements.txt`
- Create: `setup.sh`

### Task 4: tts.py

**Files:**
- Create: `hey_claude/tts.py`
- Create: `tests/test_tts.py`

### Task 5: audio.py (capture + VAD)

**Files:**
- Create: `hey_claude/audio.py`

### Task 6: stt.py (mlx-whisper)

**Files:**
- Create: `hey_claude/stt.py`

### Task 7: runner.py (Claude Code CLI)

**Files:**
- Create: `hey_claude/runner.py`
- Create: `tests/test_runner.py`

### Task 8: session.py

**Files:**
- Create: `hey_claude/session.py`
- Create: `tests/test_session.py`

### Task 9: main.py (main loop)

**Files:**
- Create: `main.py`

### Task 10: README + final wiring check

**Files:**
- Create: `README.md`

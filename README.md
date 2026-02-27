# hey-claude

Voice assistant powered by Claude Code. Say "hey claude", speak your request, and Claude executes it — with full access to your filesystem, terminal, and all Claude Code tools — then speaks the result back.

## How it works

```
"hey claude list my desktop files"
    ↓ openai-whisper (local, tiny model)
    ↓ Claude Code CLI (Vertex AI, all tools, no approval prompts)
    ↓ Bash: ls ~/Desktop
    ↓ macOS say: "You've got six things on your desktop..."
```

- **STT:** openai-whisper (local, tiny for wake word / small for commands)
- **Claude:** Claude Code CLI via subprocess (`--allowedTools` explicit list, stream-json)
- **Auth:** Vertex AI via gcloud ADC (picks up `CLAUDE_CODE_USE_VERTEX` from your shell)
- **TTS:** macOS built-in `say` (zero setup, offline)
- **Session:** Conversation context maintained for 30s between turns (say "hey claude" again after timeout)

## Setup

```bash
cd hey-claude
./setup.sh
```

First run downloads Whisper models (~500MB total) from Azure CDN.

## Run

```bash
./venv/bin/python3 main.py
```

Optional flags:
```bash
./venv/bin/python3 main.py --cwd ~/Source/Projects/my-project  # set working dir
./venv/bin/python3 main.py --voice Alex --rate 175              # different voice/speed
```

## Usage

| What you say | What happens |
|---|---|
| `hey claude list the files here` | Runs `ls`, speaks the result |
| `hey claude what's in main.go` | Reads the file, summarises it |
| `hey claude run the tests` | Runs `go test ./...` or equivalent |
| `hey claude commit everything with message fix tests` | Stages, commits, done |
| `hey claude search the web for Go context best practices` | WebSearch tool |
| (after Claude responds) `actually also check the config` | Continues session (no wake phrase) |
| `goodbye` | Ends the session, returns to wake word mode |

## Terminal output while running

```
[YOU] list the files in hey-claude
[INIT] session=abc123... tools=36
[STATUS] listing directory files      ← spoken immediately
[TOOL] Bash: ls /path/to/hey-claude   ← terminal only
[RESULT:OK] config.yaml docs hey_claude main.py ...
[SPEAK] There are nine items...        ← spoken as final response
[SESSION] Active (ID: abc123...)
```

## Configuration

Edit `config.yaml` to change:
- Voice and speech rate
- Session timeout (default 30s)
- Whisper model sizes
- Working directory

## Credentials

Reads `CLAUDE_CODE_USE_VERTEX`, `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID` from your environment (already set in `~/.zshrc`). No extra setup needed.

## Tests

```bash
./venv/bin/pytest tests/ -v
```

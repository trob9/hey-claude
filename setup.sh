#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "=== hey-claude setup ==="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install via: brew install python"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "Python: $PYTHON_VERSION"

# Check Claude Code CLI
if [ ! -f "/usr/local/bin/claude" ]; then
    echo "ERROR: Claude Code CLI not found at /usr/local/bin/claude"
    echo "Install Claude Code: https://claude.ai/code"
    exit 1
fi
echo "Claude Code CLI: $(claude --version 2>&1 | head -1)"

# Check gcloud auth
if ! gcloud auth application-default print-access-token &>/dev/null; then
    echo ""
    echo "WARNING: GCloud ADC not configured. Run:"
    echo "  gcloud auth application-default login"
    echo ""
fi

# Check Vertex env vars
if [ -z "$ANTHROPIC_VERTEX_PROJECT_ID" ]; then
    echo "WARNING: ANTHROPIC_VERTEX_PROJECT_ID not set in environment."
    echo "This should be in your ~/.zshrc already."
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo ""
echo "Installing Python dependencies..."
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install -r requirements.txt

echo ""
echo "Downloading Whisper models from Azure CDN (first run only)..."
echo "  Downloading tiny model for wake word detection (~72MB)..."
./venv/bin/python3 -c "
import warnings, whisper
warnings.filterwarnings('ignore')
whisper.load_model('tiny')
print('  tiny model ready')
"

echo "  Downloading small model for command transcription (~461MB)..."
./venv/bin/python3 -c "
import warnings, whisper
warnings.filterwarnings('ignore')
whisper.load_model('small')
print('  small model ready')
"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Run hey-claude with:"
echo "  ./venv/bin/python3 main.py"
echo ""
echo "Or add an alias to your ~/.zshrc:"
echo '  alias hey-claude="cd $SCRIPT_DIR && ./venv/bin/python3 main.py"'
echo ""

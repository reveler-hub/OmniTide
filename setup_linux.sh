#!/usr/bin/env bash
# Sets up a Python virtual environment and installs OmniTide's dependencies.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$SCRIPT_DIR/OmniTide_Env"

echo "Creating virtual environment at $ENV_DIR..."
python3 -m venv "$ENV_DIR"

echo "Installing dependencies..."
"$ENV_DIR/bin/pip" install --upgrade pip
"$ENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo
    echo "Warning: ffmpeg not found on PATH."
    echo "Install it (e.g. 'sudo apt install ffmpeg') so downloads remux correctly."
fi

chmod +x "$SCRIPT_DIR/OmniTide.py" 2>/dev/null || true

echo
echo "Setup complete."
echo "Activate the environment with:"
echo "  source $ENV_DIR/bin/activate"
echo "Then log in to Tidal with:"
echo "  ./OmniTide.py login"

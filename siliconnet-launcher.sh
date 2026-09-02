#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
MIN_PYTHON="3.10"

cd "$SCRIPT_DIR"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "SiliconNet is macOS only; this system reports $(uname -s)." >&2
    exit 1
fi

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
                command -v "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

if ! PYTHON_BIN="$(find_python)"; then
    echo "Python $MIN_PYTHON+ was not found." >&2
    echo "Install it with Homebrew (brew install python) or from python.org, then try again." >&2
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating SiliconNet virtual environment..."
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        echo "Could not create a virtual environment." >&2
        echo "If the Command Line Tools are missing, run: xcode-select --install" >&2
        exit 1
    fi
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip >/dev/null
python -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet

echo "Launching SiliconNet..."
exec python -m siliconnet "$@"

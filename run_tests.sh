#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$ROOT"

# The launcher installs the requirements into .venv; prefer that interpreter so
# the Pillow-backed icon tests run instead of being skipped.
if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

"$PYTHON_BIN" -m compileall -q siliconnet tests
"$PYTHON_BIN" -m unittest discover -s tests -v

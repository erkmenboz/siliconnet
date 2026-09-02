#!/usr/bin/env bash
# Double-clickable Finder entry point. macOS opens .command files in Terminal.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

cd "$SCRIPT_DIR"
exec ./siliconnet-launcher.sh "$@"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
VERSION="$(tr -d '\357\273\277[:space:]' < "$ROOT/VERSION")"
ARCHIVE="$ROOT/dist/siliconnet-macos-$VERSION.tar.gz"

cd "$ROOT"

python3 -m compileall -q siliconnet tests
python3 -m unittest discover -s tests -v
bash -n SiliconNet.command siliconnet-launcher.sh run_tests.sh scripts/build_macos_release.sh scripts/verify_macos_release.sh

if grep -rniE "gsettings|kwriteconfig|kreadconfig|resolvectl|xdg-open|kdialog|zenity|winreg|windll|SIGBREAK" siliconnet/; then
    echo "FAIL: non-macOS tooling referenced in siliconnet/" >&2
    exit 1
fi
echo "OK: no non-macOS tooling references"

# Catches leftover identifiers: package paths, file names, env vars, UI strings.
# README.md and CHANGELOG.md are skipped because they must name the upstream
# project for MIT attribution, and this script names it in its own check.
if grep -rnI --exclude="verify_macos_release.sh" --exclude="README.md" --exclude="CHANGELOG.md" \
    --exclude-dir="__pycache__" "CleanNet\|cleannet" siliconnet/ tests/ assets/ scripts/ *.md *.sh *.command; then
    echo "FAIL: old branding found in code or packaging" >&2
    exit 1
fi
echo "OK: no leftover branding in code or packaging"

scripts/build_macos_release.sh

if [ ! -f "$ARCHIVE" ]; then
    echo "FAIL: missing archive $ARCHIVE" >&2
    exit 1
fi

entries="$(tar -tzf "$ARCHIVE")"
for required in siliconnet assets SiliconNet.command siliconnet-launcher.sh run_tests.sh requirements.txt README.md VERSION; do
    if ! grep -q "siliconnet-macos-$VERSION/$required" <<<"$entries"; then
        echo "FAIL: missing tar entry $required" >&2
        exit 1
    fi
done

if grep -E '(__pycache__|\.pyc$|\.pyo$|\.venv/|/build/|/\._|\.DS_Store|bypass\.log|macos_proxy_state\.json|strategy_cache\.json|ai_strategy\.json|stats\.json)' <<<"$entries"; then
    echo "FAIL: archive contains forbidden runtime state or macOS metadata files" >&2
    exit 1
fi

echo "[OK] macOS release verification passed"

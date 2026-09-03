#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
VERSION="$(tr -d '\357\273\277[:space:]' < "$ROOT/VERSION")"
DIST="$ROOT/dist"
STAGE="$DIST/siliconnet-macos-$VERSION"
ARCHIVE="$DIST/siliconnet-macos-$VERSION.tar.gz"

cd "$ROOT"
./run_tests.sh

rm -rf "$STAGE" "$ARCHIVE"
mkdir -p "$STAGE" "$DIST"

cp -a siliconnet assets scripts "$STAGE/"
cp -a SiliconNet.command siliconnet-launcher.sh run_tests.sh requirements.txt README.md README.tr.md README.de.md PRIVACY.md SECURITY.md SECURITY_HARDENING.md LICENSE VERSION CHANGELOG.md RELEASE.md "$STAGE/"

find "$STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$STAGE" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
find "$STAGE" -type f -name "._*" -delete
find "$STAGE" -name ".DS_Store" -delete

chmod +x "$STAGE/SiliconNet.command" "$STAGE/siliconnet-launcher.sh" "$STAGE/run_tests.sh" "$STAGE"/scripts/*.sh

# COPYFILE_DISABLE keeps bsdtar from adding AppleDouble (._*) resource entries.
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" -C "$DIST" "siliconnet-macos-$VERSION"
if command -v shasum >/dev/null 2>&1; then
    (cd "$DIST" && shasum -a 256 "siliconnet-macos-$VERSION.tar.gz" > SHA256SUMS.txt)
else
    (cd "$DIST" && sha256sum "siliconnet-macos-$VERSION.tar.gz" > SHA256SUMS.txt)
fi
rm -rf "$STAGE"

echo "[OK] macOS release: $ARCHIVE"

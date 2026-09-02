#!/usr/bin/env bash
set -euo pipefail

python3 -m compileall -q siliconnet tests
python3 -m unittest discover -s tests -v

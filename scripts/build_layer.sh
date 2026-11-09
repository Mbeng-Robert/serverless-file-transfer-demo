#!/usr/bin/env bash
# Build the openpyxl Lambda layer (used by the merge function) into terraform/build/.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf terraform/build/layer && mkdir -p terraform/build/layer/python
pip install --quiet --target terraform/build/layer/python \
    --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 openpyxl
(cd terraform/build/layer && zip -qr ../openpyxl-layer.zip python)
echo "Built terraform/build/openpyxl-layer.zip"

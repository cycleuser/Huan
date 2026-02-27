#!/usr/bin/env bash
set -e

echo "=== Cleaning previous builds ==="
rm -rf dist/ build/ *.egg-info

echo "=== Installing build tools ==="
pip install --upgrade build twine

echo "=== Building package ==="
python -m build

echo "=== Uploading to PyPI ==="
twine upload dist/*

echo "=== Done ==="

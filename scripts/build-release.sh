#!/usr/bin/env bash
# Stamps VERSION into Core and Suite and builds every release artifact into dist/.
# Run by semantic-release (prepare step) with the computed version; also works locally.
set -euo pipefail

version="${1:?usage: $0 VERSION}"
cd "$(dirname "$0")/.."

sed -i "s/^VERSION = \".*\"/VERSION = \"$version\"/" vrgb.py
sed -i "s/^__version__ = \"[^\"]*\"/__version__ = \"$version\"/" suite/vrgb_suite/__init__.py

rm -rf dist
python3 -m pip install --quiet build
python3 -m build --outdir dist .
python3 -m build --outdir dist suite
install -m 755 vrgb.py "dist/vrgb-$version.py"

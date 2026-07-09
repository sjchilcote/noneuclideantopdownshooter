#!/usr/bin/env bash
# CI-style check: Rust engine core tests, then Python (pytest) against the
# built necore extension. Run from the repo root.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "== cargo test -p necore =="
(cd engine && cargo test -p necore)

echo "== maturin develop --release (rebuild necore extension) =="
uv run maturin develop --release -m engine/necore-py/Cargo.toml -q

echo "== uv run pytest -q =="
uv run pytest -q

echo "== check.sh: all green =="

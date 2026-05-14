#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

OUTPUT="${1:-dist/public-export}"

uv run python scripts/release/create_public_export.py --output "$OUTPUT"
uv run python scripts/security/prepare_public_export_check.py "$OUTPUT"


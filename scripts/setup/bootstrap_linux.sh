#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 not found. $2 Run: bash scripts/deploy/portable_deploy.sh --install-missing" >&2
    exit 1
  fi
}

WITH_DOCUMENT_READER="${WITH_DOCUMENT_READER:-0}"

need uv "Install uv from https://docs.astral.sh/uv/"
need node "Install Node.js 20+."
need npm "Install Node.js 20+."

if [ ! -f .env ]; then
  cp .env.linux.example .env
  echo "Created .env from .env.linux.example. Edit it before public use."
fi

mkdir -p data/indexes data/sqlite data/feedback data/logs data/runtime_logs \
  data/screenshots data/cache data/eval_reports models/ollama models/huggingface \
  models/document_reader logs

if [ "$WITH_DOCUMENT_READER" = "1" ]; then
  uv sync --extra dev --extra document-reader
else
  uv sync --extra dev
fi

(cd app/frontend && npm install)

echo "Bootstrap complete. Next: bash scripts/models/pull_required_models.sh"

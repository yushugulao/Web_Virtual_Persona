#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

MODELS=("$@")
if [ "${#MODELS[@]}" -eq 0 ]; then
  MODELS=("qwen3.5:9b" "qwen3-embedding:0.6b")
fi

mkdir -p models/ollama models/logs
export OLLAMA_MODELS="$ROOT/models/ollama"

OLLAMA_BIN="${PERSONA_RAG_OLLAMA_EXECUTABLE:-}"
if [ -n "$OLLAMA_BIN" ] && [ ! -x "$OLLAMA_BIN" ]; then
  echo "PERSONA_RAG_OLLAMA_EXECUTABLE is set but not executable: $OLLAMA_BIN" >&2
  exit 1
fi
if [ -z "$OLLAMA_BIN" ]; then
  if command -v ollama >/dev/null 2>&1; then
    OLLAMA_BIN="$(command -v ollama)"
  else
    echo "Ollama executable not found." >&2
    echo "Run: bash scripts/deploy/portable_deploy.sh --install-missing" >&2
    echo "Or set PERSONA_RAG_OLLAMA_EXECUTABLE to an existing ollama binary." >&2
    exit 1
  fi
fi

if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Starting ollama serve in background."
  nohup "$OLLAMA_BIN" serve >models/logs/ollama.out.log 2>models/logs/ollama.err.log &
  sleep 3
fi

for model in "${MODELS[@]}"; do
  echo "Pulling $model"
  "$OLLAMA_BIN" pull "$model"
done

"$OLLAMA_BIN" list

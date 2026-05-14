# Local model workspace

This directory is intentionally excluded from Git except for this README and `.gitkeep` placeholders.

Put local model caches here:

- `models/ollama` for Ollama models.
- `models/huggingface` for optional Hugging Face caches.
- `models/document_reader` for OCR/VLM worker runtimes and caches.

Use the helper scripts instead of committing model weights:

```powershell
.\scripts\models\pull_required_models.ps1
```

```bash
bash scripts/models/pull_required_models.sh
```

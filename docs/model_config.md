# 模型配置

项目默认走 Ollama，本地模型目录由 `scripts/models/set_model_cache_env.ps1` 或对应 shell 脚本设置到项目 `models/ollama`。

推荐模型：

```text
qwen3.5:9b
qwen3-embedding:0.6b
```

部署向导内置四个 profile：

- `standard_gpu`：推荐给 12GB+ VRAM 的 NVIDIA GPU，使用 `qwen3.5:9b` 和 `qwen3-embedding:0.6b`。
- `quick_gpu`：低带宽或首次公网 smoke 推荐，只拉取较小的 `qwen3:0.6b`，并在 smoke 部署中临时复用它做生成与检索向量；它仍然从公开模型源下载，不会导入已有 Ollama 缓存。
- `minimal_cpu`：给 CPU-only 或低显存机器，使用较轻模型路线，速度较慢。
- `no_model_dev`：用于 CI、前端和 API 开发，不拉取模型。

拉取模型：

```powershell
.\scripts\models\pull_required_models.ps1
```

或：

```bash
bash scripts/models/pull_required_models.sh
```

如果机器上还没有 Ollama，先运行部署向导安装缺失依赖：

```powershell
.\scripts\deploy\portable_deploy.ps1 -InstallMissing
```

```bash
bash scripts/deploy/portable_deploy.sh --install-missing
```

模型拉取过程会显示 Ollama 的下载阶段和进度。若 Ollama registry 下载失败，部署器会继续尝试
`configs/model_sources.json` 中登记的替代路径：Ollama 的 Hugging Face GGUF 入口，以及直接下载
GGUF 后用 `ollama create` 导入。若所有来源都失败，可以重新运行模型脚本，或重新运行部署向导
选择更小的 `quick_gpu` / `minimal_cpu` / `no_model_dev` profile。

`.env` 中常用配置：

```env
PERSONA_RAG_MODEL_PROVIDER=ollama
PERSONA_RAG_OLLAMA_BASE_URL=http://127.0.0.1:11434
PERSONA_RAG_LOW_GENERATION_MODEL=qwen3.5:9b
PERSONA_RAG_MEDIUM_GENERATION_MODEL=qwen3.5:9b
PERSONA_RAG_EMBEDDING_MODEL=qwen3-embedding:0.6b
```

高努力模型可以按机器显存自行配置。模型权重不随开源仓库发布。

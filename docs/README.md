# Web虚拟分身

`Web虚拟分身` 是一个本地优先的虚拟分身 / Persona-RAG 项目。它提供浏览器聊天界面、FastAPI 后端、可审计资料库、会话记忆、用户自建分身入口，以及面向 PDF、Office、图片、截图和代码材料的多模态文件读取器。

项目默认使用本地 Ollama 模型，不要求把私人资料上传到第三方模型服务。DeepSeek 等外部 API 只作为后续可选的信息整理能力，密钥必须由部署者自己放入本地 `.env`，不会随仓库发布。

## 能做什么

- 与公开虚拟分身对话，支持证据检索、引用和会话恢复。
- 登录后管理自己的会话，每个会话有独立记忆，同时支持用户级共享记忆。
- 上传资料创建个人虚拟分身草稿，文件读取器会生成 Markdown、结构块和 provenance。
- 在 Windows 或 Linux 上本地运行前后端和 Ollama 模型。
- 用测试台、安全扫描和导出检查保护开源发布质量。

## 快速开始

Windows:

```powershell
.\scripts\deploy\portable_deploy.ps1 -Mode local_lan -InstallMissing
.\scripts\setup\bootstrap_windows.ps1
.\scripts\models\pull_required_models.ps1
.\scripts\dev\start_all_windows.ps1
```

Linux:

```bash
bash scripts/deploy/portable_deploy.sh --mode local_lan --install-missing
bash scripts/setup/bootstrap_linux.sh
bash scripts/models/pull_required_models.sh
bash scripts/dev/start_all_linux.sh
```

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`
- Ollama：`http://127.0.0.1:11434`

## 最小依赖

- Python 3.11+
- uv（部署向导可安装）
- Node.js 20+（部署向导可安装）
- Ollama（部署向导可安装并拉取模型）

推荐模型：

- 对话模型：`qwen3.5:9b`
- 兜底模型：`qwen3:8b`
- 嵌入模型：`qwen3-embedding:0.6b`

部署向导会检测内存、磁盘、Ollama、NVIDIA GPU 和 VRAM，然后推荐：

- `standard_gpu`：适合约 12GB+ VRAM 的 NVIDIA GPU，默认 Qwen3.5 9B。
- `minimal_cpu`：适合没有足够 GPU 的机器，能跑但可能较慢。
- `no_model_dev`：只用于 UI/API/CI，不提供完整本地聊天。

Marker/Surya CUDA OCR、远程公网部署和内网穿透都属于可选增强。

如果缺少 uv、Node.js、Git、Ollama、frp 或 Linux Nginx，部署向导可以从官方来源生成安装计划并下载安装。下载过程会显示进度、速度和 ETA；下载缓存与安装报告只保存在本机 `.deploy/portable/`。

## 安全与隐私

- `.env`、模型、SQLite、缓存、截图、评测报告不应提交到 Git。
- API Key、SMTP 授权码、服务器密码只允许在本机秘密配置中存在。
- 发布前运行：

```bash
uv run python scripts/security/scan_secrets.py --tracked --fail-on-high
uv run python scripts/security/prepare_public_export_check.py dist/public-export
```

## 开源发布方式

不要直接推送本地研发仓库的全部历史。推荐先生成干净导出目录：

```powershell
.\scripts\release\create_public_export.ps1
```

或：

```bash
bash scripts/release/create_public_export.sh
```

然后将 `dist/public-export/` 初始化为新的 GitHub 仓库。

## 公网部署

部署向导支持两条公网路线：

- `direct_public_server`：整套服务直接部署到资源足够的 Linux 公网服务器。
- `frp_tunnel`：公网服务器只运行 Nginx + frps，本地机器运行后端、Ollama 和私有数据。

真实服务器地址、frp token、SMTP 密码和 API key 都只写入本机 `.env` 或 `.deploy/`，不应出现在 GitHub 仓库中。

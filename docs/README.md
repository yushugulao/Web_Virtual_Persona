# Web虚拟分身

`Web虚拟分身` 是一个可以在 Windows 或 Linux 上部署的虚拟分身平台。你可以与公开分身对话，也可以上传资料创建自己的分身，并把分身发布到社区中共享。

## Windows 图形化本地快速部署

在 Windows PowerShell 中运行以下命令，会打开图形化本地部署界面。你可以在界面中选择安装目录、
仓库分支、模型配置、账号和端口；点击“开始部署”后，系统会下载项目并在本机 `127.0.0.1`
启动前端与后端：

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/bootstrap.ps1 | iex"
```

默认安装目录是 `C:\WebVirtualPersona`，也可以直接在图形界面里改。如果想提前指定默认值，可以先设置环境变量：

```powershell
$env:WEB_VIRTUAL_PERSONA_DIR="$HOME\WebVirtualPersona"
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/bootstrap.ps1 | iex"
```

图形界面会让你选择安装目录、仓库/分支、覆盖策略、模型配置、管理员账号、端口、Ollama URL、SQLite 路径、文档读取/OCR 能力、DeepSeek/SMTP 配置、是否安装依赖、是否拉取模型，以及是否自动打开浏览器。基础文档读取默认安装；Marker/Surya 和 PaddleOCR-VL 这类较大的 OCR 运行时只有勾选后才会下载、安装和预热。
首次体验建议选择 `快速体验：Qwen3 0.6B`，下载小，能更快验证完整链路。完成后访问：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`
- 默认用户名：`admin`
- 默认密码：图形界面中填写的管理员密码

## 命令行部署入口

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/install.sh | bash
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/bootstrap.ps1 | iex"
```

Windows 下该命令默认打开图形化本地部署界面。如果需要命令行部署，可设置
`WEB_VIRTUAL_PERSONA_NO_GUI=1` 后再运行。

Linux / macOS 安装入口会自动下载项目代码，然后启动命令行部署工具。它会检测你的系统、GPU、内存、磁盘、Python、uv、Node.js、Ollama、frp 等环境，缺什么就提示安装什么，并在下载依赖和模型时显示进度。

## 部署方式

部署工具会让你选择一种运行方式。

### 本机 / 局域网部署

适合先在自己的电脑上试用。前端、后端、Ollama 模型和数据库都在当前机器上运行。

```bash
python scripts/deploy/portable_deploy.py --mode local_lan --install-missing
```

启动后通常访问：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8001`
- Ollama：`http://127.0.0.1:11434`

### 公网服务器直接部署

适合资源充足的 Linux 公网服务器。服务器会同时运行 Nginx、前端静态资源、FastAPI 后端和 Ollama 模型。

```bash
python scripts/deploy/portable_deploy.py --mode direct_public_server --install-missing
```

如果服务器只有公网 IP，没有域名，部署工具会提示使用自签 HTTPS；如果有域名，建议接入正式证书。

### 算力服务器后端 + 公网入口部署

适合“算力服务器跑模型，轻量公网服务器只负责入口”的结构。算力服务器运行后端和 Ollama，公网服务器运行 Nginx + frps，通过 frp 把公网请求转发到算力服务器后端。

```bash
python scripts/deploy/portable_deploy.py \
  --mode compute_backend_frp \
  --profile standard_gpu \
  --install-missing \
  --pull-models
```

部署工具会要求你填写：

- 公网服务器地址或域名
- frps 端口
- frp token
- 公网入口 URL
- 映射到公网服务器本机的 remote port

公网服务器上的 Nginx 应代理到 `127.0.0.1:<remote_port>`。

### 内网穿透部署

适合在自己的电脑上跑后端和模型，但希望外网可以访问。公网服务器运行 Nginx + frps，本机运行后端、Ollama 和 frpc。

```bash
python scripts/deploy/portable_deploy.py --mode frp_tunnel --install-missing
```

## 模型选择

部署工具会根据机器条件推荐模型配置：

- `standard_gpu`：有 NVIDIA GPU 且显存较充足，默认使用 Qwen3.5 9B。
- `quick_gpu`：低带宽或首次公网 smoke 推荐，使用紧凑 Qwen3 0.6B，仍然从公开模型源下载。
- `minimal_cpu`：没有合适 GPU 时使用，速度较慢。
- `no_model_dev`：只部署界面和 API，不拉取本地大模型，适合开发或排查环境。

你也可以在部署时手动指定：

```bash
python scripts/deploy/portable_deploy.py --profile standard_gpu --pull-models
```

模型由 Ollama 管理，部署工具会列出需要拉取的模型，并显示下载状态。若 Ollama
官方 registry 下载失败，部署器会继续尝试 `configs/model_sources.json` 中登记的替代
来源：先试 Ollama 的 Hugging Face GGUF 入口，再试直接下载 GGUF 并通过
`ollama create` 导入为项目需要的模型名。

## 常见问题

### Ollama 没有启动

先检查：

```bash
curl http://127.0.0.1:11434/api/tags
```

如果失败，重新运行部署工具并选择安装/启动 Ollama。

### 模型下载很慢

部署器会按顺序尝试多个来源，并保留下载进度、速度和 ETA。若所有来源都失败，
可以先切到 `quick_gpu` 验证完整小模型链路，或者切到 `no_model_dev` 只验证部署链路。之后再用
`--pull-models` 单独拉取模型。

### 端口被占用

检查：

```bash
ss -lntp | grep -E ':8001|:11434|:7000|:18001'
```

Windows 可用：

```powershell
netstat -ano | findstr "8001 11434 7000 18001"
```

### frp 连不上

确认公网服务器安全组已经放行 frps 端口，frp token 一致，并且公网服务器上的 frps 正在运行。

### 公网页面 502 或 `/health` 失败

按顺序检查：

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:<remote_port>/health
nginx -t
```

如果第一步失败，问题在后端或模型服务器；如果第二步失败，问题在 frp；如果第三步失败，问题在 Nginx 配置。

# Web虚拟分身

`Web虚拟分身` 是一个可以在 Windows 或 Linux 上部署的虚拟分身平台。你可以与公开分身对话，也可以上传资料创建自己的分身，并把分身发布到社区中共享。

## 一行快速部署

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/install.sh | bash
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/install.ps1 | iex"
```

安装入口会自动下载项目代码，然后启动部署向导。向导会检测你的系统、GPU、内存、磁盘、Python、uv、Node.js、Ollama、frp 等环境，缺什么就提示安装什么，并在下载依赖和模型时显示进度。

## 部署方式

部署向导会让你选择一种运行方式。

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

如果服务器只有公网 IP，没有域名，向导会提示使用自签 HTTPS；如果有域名，建议接入正式证书。

### 算力服务器后端 + 公网入口部署

适合“算力服务器跑模型，轻量公网服务器只负责入口”的结构。算力服务器运行后端和 Ollama，公网服务器运行 Nginx + frps，通过 frp 把公网请求转发到算力服务器后端。

```bash
python scripts/deploy/portable_deploy.py \
  --mode compute_backend_frp \
  --profile standard_gpu \
  --install-missing \
  --pull-models
```

向导会要求你填写：

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

部署向导会根据机器条件推荐模型配置：

- `standard_gpu`：有 NVIDIA GPU 且显存较充足，默认使用 Qwen3.5 9B。
- `minimal_cpu`：没有合适 GPU 时使用，速度较慢。
- `no_model_dev`：只部署界面和 API，不拉取本地大模型，适合开发或排查环境。

你也可以在部署时手动指定：

```bash
python scripts/deploy/portable_deploy.py --profile standard_gpu --pull-models
```

模型由 Ollama 管理，向导会列出需要拉取的模型，并显示下载状态。

## 常见问题

### Ollama 没有启动

先检查：

```bash
curl http://127.0.0.1:11434/api/tags
```

如果失败，重新运行部署向导并选择安装/启动 Ollama。

### 模型下载很慢

可以先切到 `no_model_dev` 验证部署链路，或者换成更小的模型配置。之后再用 `--pull-models` 单独拉取模型。

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

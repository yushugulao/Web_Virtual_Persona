# 部署指南

本项目推荐先通过部署向导完成环境检测、模型选择和 `.env` 生成：

Windows:

```powershell
.\scripts\deploy\portable_deploy.ps1 -Mode local_lan
```

Linux:

```bash
bash scripts/deploy/portable_deploy.sh --mode local_lan
```

向导会检测 Python、uv、Node.js、npm、Git、Ollama、NVIDIA GPU、VRAM、Nginx、systemd、SSH 和 frp，然后推荐 `standard_gpu`、`minimal_cpu` 或 `no_model_dev`。
加上 `--install-missing`（Windows 包装脚本参数为 `-InstallMissing`）后，向导会对缺失依赖生成安装计划，并从官方来源下载安装。下载进度、速度、ETA 和安装结果会显示在终端，安装日志写入 `.deploy/portable/install_report.json`。

## 部署模式

### 本机 / 局域网

适合个人电脑或实验室机器。后端、前端、Ollama 和 SQLite 都在当前机器运行。

```powershell
.\scripts\deploy\portable_deploy.ps1 -Mode local_lan -InstallMissing
.\scripts\setup\bootstrap_windows.ps1
.\scripts\models\pull_required_models.ps1
.\scripts\dev\start_all_windows.ps1
```

```bash
bash scripts/deploy/portable_deploy.sh --mode local_lan --install-missing
bash scripts/setup/bootstrap_linux.sh
bash scripts/models/pull_required_models.sh
bash scripts/dev/start_all_linux.sh
```

### 公网服务器直接部署

适合资源足够的 Linux 服务器。服务器需要能运行本地模型，建议至少 24GB 内存，最好有 NVIDIA GPU。向导会生成本地 `.env` 覆盖项，并给出 Nginx / systemd 后续命令。

```bash
bash scripts/deploy/portable_deploy.sh --mode direct_public_server
```

可参考：

- `deploy/public/nginx-web-avatar-direct.conf.example`
- `deploy/public/web-avatar-backend.service.example`

### 内网穿透

适合轻量公网服务器。公网服务器只提供 Nginx + frps，模型、后端和私有数据仍在本机。

Windows:

```powershell
.\scripts\deploy\portable_deploy.ps1 -Mode frp_tunnel
```

随后可使用现有脚本初始化服务器和发布前端：

```powershell
.\scripts\deploy\bootstrap_public_ecs_frp.ps1 -ServerHost <PUBLIC_SERVER_IP>
.\scripts\deploy\deploy_public_demo.ps1 -ServerHost <PUBLIC_SERVER_IP>
```

公开仓库只提供占位配置：

- `<PUBLIC_SERVER_IP>`
- `<DOMAIN>`
- `<REMOTE_USER>`
- `<FRP_TOKEN>`

真实 IP、域名、服务器用户、证书私钥和 token 必须放在本机 `.env`、服务器私有配置或受控密钥管理中，不应提交到 Git。

### AutoDL / SeetaCloud 后端 + ECS 公网入口

如果本机 GPU 不适合长期在线，可以把后端和 Ollama 迁到 AutoDL / SeetaCloud 这类算力服务器，
同时继续使用轻量 ECS 做 Nginx + frps 公网入口：

```powershell
.\scripts\deploy\deploy_public_autodl_demo.ps1 `
  -ServerHost <PUBLIC_SERVER_IP> `
  -AutodlHost <AUTODL_SSH_HOST> `
  -AutodlPort <AUTODL_SSH_PORT> `
  -AutodlUser root
```

首次使用前需要安装一次 AutoDL SSH key。完整流程见
`docs/public/autodl_backend_deployment.md`。

## HTTPS

- 有域名时优先使用 Let’s Encrypt。
- 只有 IP 时可以使用自签证书，浏览器证书警告是预期现象。
- 生产环境建议前端和 API 同源访问，由 Nginx 代理 `/chat/stream` 等 SSE 路径，并关闭该路径的代理缓冲。

公网部署前至少执行：

```bash
uv run python scripts/security/prepare_public_export_check.py dist/public-export
```

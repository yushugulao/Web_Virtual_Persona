# AutoDL 后端 + 阿里云公网入口部署

本部署模式用于临时演示或轻量公网访问：

- AutoDL / SeetaCloud 算力服务器运行 FastAPI 后端、Ollama 和本地模型。
- 阿里云 ECS 只运行 Nginx + frps，继续作为 `https://<PUBLIC_SERVER_IP>/` 公网入口。
- frp 把 ECS 本机 `127.0.0.1:18001` 转发到 AutoDL 后端 `127.0.0.1:8001`。
- 默认新建远端数据库，不迁移本机用户、会话、上传文件和 SQLite。

## 一次性准备

先确保阿里云 ECS 已完成原有公网入口初始化：

```powershell
.\scripts\deploy\bootstrap_public_ecs_frp.ps1 -ServerHost <PUBLIC_SERVER_IP>
```

AutoDL 首次部署需要把本机 SSH key 写入远端 root 的 `authorized_keys`。脚本支持读取当前
PowerShell 环境变量里的 root 密码，但不会把密码写入文件：

```powershell
$env:PERSONA_RAG_AUTODL_ROOT_PASSWORD = "<AUTODL_ROOT_PASSWORD>"
.\scripts\deploy\bootstrap_autodl_backend.ps1 `
  -AutodlHost connect.bjb2.seetacloud.com `
  -AutodlPort 25163 `
  -AutodlUser root `
  -InstallKeyWithPassword
Remove-Item Env:PERSONA_RAG_AUTODL_ROOT_PASSWORD
```

之后部署全程使用 `secrets/autodl_backend/autodl_backend_ed25519`，不再需要密码。

## 一键部署

```powershell
.\scripts\deploy\deploy_public_autodl_demo.ps1 `
  -ServerHost <PUBLIC_SERVER_IP> `
  -AutodlHost connect.bjb2.seetacloud.com `
  -AutodlPort 25163 `
  -AutodlUser root
```

脚本会执行：

1. 停止本机旧 frpc / reverse-SSH 公网隧道，避免抢占 ECS `18001`。
2. 检查 ECS frps 与 Nginx。
3. 构建并发布前端到 ECS。
4. 生成 sanitized public export 并上传到 AutoDL。
5. 在 AutoDL 安装依赖、安装/启动 Ollama、拉取模型、启动 FastAPI。
6. 在 AutoDL 启动 frpc，连接 ECS frps。
7. 验证 ECS loopback `/health` 与公网 `/health`。

默认管理员账号是 `admin`。如果没有设置 `PERSONA_RAG_AUTODL_ADMIN_PASSWORD`，脚本会生成一个
新密码并写入本机忽略目录：

```text
.deploy/autodl/admin_credentials.txt
```

## 常用排障

AutoDL 后端健康：

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:11434/api/tags
tail -120 /opt/web-avatar/backend/logs/backend.err.log
tail -120 /opt/web-avatar/backend/logs/frpc.err.log
```

ECS 公网入口健康：

```bash
systemctl is-active frps
ss -lntp | grep 7000
curl http://127.0.0.1:18001/health
nginx -t
```

公网：

```powershell
Invoke-WebRequest -SkipCertificateCheck https://<PUBLIC_SERVER_IP>/health
```

## 数据迁移

本模式默认是新环境部署。若后续需要迁移本机用户、会话、上传文件和用户分身资料，应单独做
SQLite 与 `data/user_personas/`、`corpus/user_personas/` 的备份/恢复脚本，不建议混入首次部署。

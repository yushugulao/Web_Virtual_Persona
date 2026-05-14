# 内网穿透部署

内网穿透模式用于低配公网服务器：服务器只运行 Nginx 和 frps，本地机器继续运行 FastAPI、Ollama、SQLite、模型和私有资料。

## 需要准备

- 一台公网 Linux 服务器。
- 服务器开放 `443/tcp` 和 frp 服务端口，例如 `7000/tcp`。
- 本地机器能 SSH 到服务器。
- 一个 frp token。可以由脚本生成，也可以由部署者自行填写。

## Windows 本地部署

```powershell
.\scripts\deploy\portable_deploy.ps1 -Mode frp_tunnel
.\scripts\deploy\bootstrap_public_ecs_frp.ps1 -ServerHost <PUBLIC_SERVER_IP>
.\scripts\deploy\deploy_public_demo.ps1 -ServerHost <PUBLIC_SERVER_IP>
```

## Linux 本地部署

Linux 用户可以先用部署向导生成 `.env` 和本地配置，然后参考 `deploy/public/` 中的 frp / Nginx 模板手动部署服务器端。后续可把同等自动化扩展到 shell 脚本。

## 安全边界

- 不开放本机 Ollama、SQLite 或后端端口到公网。
- frp 的远端后端端口应只绑定服务器 loopback。
- 服务器密码、SSH key、frp token 和证书私钥不得提交到 Git。

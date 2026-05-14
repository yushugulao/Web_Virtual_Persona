# 密钥与公开发布安全

本项目可以作为开源项目发布，但真实运行密钥必须留在部署者本机。

## 可以进入 Git 的内容

- `.env.example`、`.env.windows.example`、`.env.linux.example` 中的占位符。
- 公开默认分身的 reviewed corpus。
- 部署脚本、Nginx/frp 模板和测试。

## 不应进入 Git 的内容

- `.env`
- `.deploy/`
- SQLite 数据库。
- Ollama/Marker/Surya 等模型文件。
- DeepSeek API key。
- SMTP 授权码。
- 服务器密码、SSH 私钥、frp token、证书私钥。
- 用户上传文件、用户自建分身 corpus、eval reports 和截图。

## 发布前检查

```bash
uv run python scripts/security/scan_secrets.py --tracked --fail-on-high
uv run python scripts/release/create_public_export.py
uv run python scripts/security/prepare_public_export_check.py dist/public-export
```

推荐从 `dist/public-export/` 初始化新的 GitHub 仓库，而不是直接推送本地研发仓库历史。

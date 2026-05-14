# 故障排查

## 前端打不开

确认 Vite 已启动：

```bash
cd app/frontend
npm run dev
```

## 后端打不开

确认后端已启动：

```bash
uv run uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

## 模型不可用

确认 Ollama 正在监听：

```bash
ollama list
```

确认 `.env` 中的模型名已经拉取。

也可以先运行部署向导查看推荐 profile：

```bash
uv run python scripts/deploy/portable_deploy.py --dry-run --non-interactive
```

如果机器没有足够 GPU 或内存，选择 `minimal_cpu` 或 `no_model_dev`。

## 部署向导没有安装系统软件

部署向导默认先检查环境并给出下一步命令，不会静默安装系统包。缺少 Python、uv、Node.js、Ollama、Nginx 或 frp 时，按向导输出安装后再重跑。

## 注册邮件失败

SMTP 账号、授权码和发信地址必须写入本机 `.env`。不要把它们写入 `.env.example` 或文档。

## 文档 OCR 很慢

Docling 适合数字 PDF 和 Office 文档。扫描件和图片建议启用 Marker/Surya worker；CUDA 运行时需要本机 GPU 和匹配的 PyTorch CUDA wheel。

# 安装指南

## Windows

1. 安装 Python 3.11+。
2. 运行部署向导检测机器。若缺少 uv、Node.js、Git、Ollama 或 frp，可让向导从官方来源下载安装。
3. 运行 bootstrap 安装 Python / Node 依赖。
4. 拉取推荐模型并启动服务。

```powershell
.\scripts\deploy\portable_deploy.ps1 -Mode local_lan -InstallMissing
.\scripts\setup\bootstrap_windows.ps1
.\scripts\models\pull_required_models.ps1
.\scripts\dev\start_all_windows.ps1
```

## Linux

1. 安装 Python 3.11+。
2. 运行部署向导检测机器。若缺少 uv、Node.js、Git、Ollama、Nginx 或 frp，可让向导从官方来源或系统包管理器安装。
3. 运行 bootstrap 安装 Python / Node 依赖。
4. 拉取推荐模型并启动服务。

```bash
bash scripts/deploy/portable_deploy.sh --mode local_lan --install-missing
bash scripts/setup/bootstrap_linux.sh
bash scripts/models/pull_required_models.sh
bash scripts/dev/start_all_linux.sh
```

安装器下载缓存和安装报告只写入 `.deploy/portable/`，不会进入 Git。

## 部署向导 dry-run

如果只想看环境检测和推荐结果，不写入 `.env`：

```powershell
.\scripts\deploy\portable_deploy.ps1 -DryRun -NonInteractive
```

```bash
bash scripts/deploy/portable_deploy.sh --dry-run --non-interactive
```

如果只想预览缺失依赖的联网安装计划，不下载、不安装：

```powershell
.\scripts\deploy\portable_deploy.ps1 -DryRunInstall
```

```bash
bash scripts/deploy/portable_deploy.sh --dry-run-install
```

## 可选 OCR/VLM

Docling 是默认文档解析后端。Marker/Surya 可以作为扫描 PDF、图片、截图、表格、公式和图表的增强 OCR/VLM 后端。Windows CUDA 环境可参考 `docs/public/document_reader.md`。

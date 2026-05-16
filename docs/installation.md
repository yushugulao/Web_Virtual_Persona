# 安装指南

## Windows

推荐先使用图形化本地快速部署。一行命令只下载小型启动包和 GUI 脚本；GUI 打开后，你可以选择安装目录、仓库分支、覆盖策略、模型配置、账号、端口、Ollama URL、SQLite 路径、可选 DeepSeek/SMTP 配置，并引导安装 uv、Node.js/npm、Ollama、项目依赖和模型。主项目代码会在你点击开始后才下载。

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/install.ps1 | iex"
```

默认安装目录是 `C:\WebVirtualPersona`，也可以直接在 GUI 里修改。如需提前指定默认目录：

```powershell
$env:WEB_VIRTUAL_PERSONA_DIR="C:\WebVirtualPersona"
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/install.ps1 | iex"
```

GUI 完成后会自动打开：

```text
http://127.0.0.1:5173
```

登录用户名是 `admin`，密码是 GUI 中填写的管理员密码。

也可以使用原命令行流程：

```powershell
.\scripts\deploy\portable_deploy.ps1 -Mode local_lan -InstallMissing
.\scripts\setup\bootstrap_windows.ps1
.\scripts\models\pull_required_models.ps1
.\scripts\dev\start_all_windows.ps1
```

如果从一行安装入口启动但想使用命令行向导：

```powershell
$env:WEB_VIRTUAL_PERSONA_NO_GUI="1"
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/yushugulao/Web_Virtual_Persona/main/install.ps1 | iex"
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

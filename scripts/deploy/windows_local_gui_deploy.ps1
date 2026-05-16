param(
  [string]$ProjectRoot = "",
  [string]$DefaultProjectRoot = "",
  [string]$Repo = $env:WEB_VIRTUAL_PERSONA_REPO,
  [string]$Branch = $env:WEB_VIRTUAL_PERSONA_BRANCH,
  [switch]$Replace
)

$ErrorActionPreference = "Stop"

if (-not ($PSVersionTable.PSVersion.Major -ge 5)) {
  throw "PowerShell 5.1 or newer is required."
}
if (-not $Repo) { $Repo = "yushugulao/Web_Virtual_Persona" }
if (-not $Branch) { $Branch = "main" }
if (-not $DefaultProjectRoot) { $DefaultProjectRoot = $env:WEB_VIRTUAL_PERSONA_DIR }
if (-not $DefaultProjectRoot) { $DefaultProjectRoot = "C:\WebVirtualPersona" }
if (-not $ProjectRoot) { $ProjectRoot = $DefaultProjectRoot }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

function Test-ProjectDirectory([string]$Path) {
  return (Test-Path -LiteralPath (Join-Path $Path "pyproject.toml")) -and
    (Test-Path -LiteralPath (Join-Path $Path "app\frontend\package.json")) -and
    (Test-Path -LiteralPath (Join-Path $Path "scripts\deploy"))
}

function New-Label([string]$Text, [int]$X, [int]$Y, [int]$W = 160, [int]$H = 24) {
  $label = New-Object System.Windows.Forms.Label
  $label.Text = $Text
  $label.Location = New-Object System.Drawing.Point($X, $Y)
  $label.Size = New-Object System.Drawing.Size($W, $H)
  return $label
}

function New-CheckBox([string]$Text, [int]$X, [int]$Y, [bool]$Checked = $true, [int]$W = 520) {
  $box = New-Object System.Windows.Forms.CheckBox
  $box.Text = $Text
  $box.Location = New-Object System.Drawing.Point($X, $Y)
  $box.Size = New-Object System.Drawing.Size($W, 24)
  $box.Checked = $Checked
  return $box
}

function Write-RunnerScript([string]$Path) {
  $runner = @'
param(
  [Parameter(Mandatory = $true)]
  [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$cfg = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$ProjectRoot = [string]$cfg.project_root
$Repo = [string]$cfg.repo
$Branch = [string]$cfg.branch

function Step([string]$Message) {
  Write-Host ""
  Write-Host "==> $Message"
}

function Refresh-Path {
  $candidates = @(
    "$env:USERPROFILE\.local\bin",
    "$env:USERPROFILE\.cargo\bin",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps",
    "$env:LOCALAPPDATA\Programs\Ollama",
    "$env:LOCALAPPDATA\Programs\Python\Python311",
    "$env:LOCALAPPDATA\Programs\Python\Python311\Scripts",
    "$env:ProgramFiles\nodejs"
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
  if ($candidates.Count -gt 0) {
    $env:PATH = (($candidates + ($env:PATH -split ';')) | Select-Object -Unique) -join ';'
  }
}

function Has-Command([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Require-Winget {
  if (-not (Has-Command "winget")) {
    throw "winget was not found. Install dependencies manually or install Windows App Installer from Microsoft Store."
  }
}

function Test-ProjectDirectory([string]$Path) {
  return (Test-Path -LiteralPath (Join-Path $Path "pyproject.toml")) -and
    (Test-Path -LiteralPath (Join-Path $Path "app\frontend\package.json")) -and
    (Test-Path -LiteralPath (Join-Path $Path "scripts\deploy"))
}

function Download-ProjectSource {
  if ((Test-ProjectDirectory $ProjectRoot) -and -not $cfg.replace_existing) {
    Write-Host "Using existing project directory: $ProjectRoot"
    return
  }
  if ((Test-Path -LiteralPath $ProjectRoot) -and -not $cfg.replace_existing -and -not (Test-ProjectDirectory $ProjectRoot)) {
    $children = @(Get-ChildItem -LiteralPath $ProjectRoot -Force -ErrorAction SilentlyContinue)
    if ($children.Count -gt 0) {
      throw "Install directory exists and is not empty. Enable replace existing directory or choose another path."
    }
  }

  $url = "https://codeload.github.com/$Repo/zip/refs/heads/$Branch"
  $temp = Join-Path ([System.IO.Path]::GetTempPath()) ("web-avatar-source-" + [System.Guid]::NewGuid().ToString("N"))
  $zipPath = Join-Path $temp "source.zip"
  Step "Downloading project source from $Repo@$Branch"
  New-Item -ItemType Directory -Force -Path $temp | Out-Null
  try {
    Invoke-WebRequest -Uri $url -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $temp -Force
    $extracted = Get-ChildItem -Path $temp -Directory |
      Where-Object { $_.Name -like "*Web_Virtual_Persona*" -or $_.Name -like "*-$Branch" } |
      Select-Object -First 1
    if (-not $extracted) {
      $extracted = Get-ChildItem -Path $temp -Directory | Select-Object -First 1
    }
    if (-not $extracted) {
      throw "Downloaded archive did not contain a project directory."
    }
    if ((Test-Path -LiteralPath $ProjectRoot) -and $cfg.replace_existing) {
      Remove-Item -LiteralPath $ProjectRoot -Recurse -Force
    } elseif ((Test-Path -LiteralPath $ProjectRoot) -and -not (Test-ProjectDirectory $ProjectRoot)) {
      $children = @(Get-ChildItem -LiteralPath $ProjectRoot -Force -ErrorAction SilentlyContinue)
      if ($children.Count -eq 0) {
        Remove-Item -LiteralPath $ProjectRoot -Force
      }
    }
    if (-not (Test-Path -LiteralPath $ProjectRoot)) {
      $parent = Split-Path -Parent $ProjectRoot
      if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
      Move-Item -LiteralPath $extracted.FullName -Destination $ProjectRoot
    }
  } finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Find-Ollama {
  $cmd = Get-Command ollama -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($candidate in @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "$env:ProgramFiles\Ollama\ollama.exe",
    "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama.exe"
  )) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  return $null
}

function Ensure-Uv {
  Refresh-Path
  if (Has-Command "uv") {
    Write-Host "uv is available: $((Get-Command uv).Source)"
    return
  }
  if (-not $cfg.install_tools) {
    throw "uv is missing. Enable dependency installation in the GUI or install uv manually."
  }
  Step "Installing uv from official Astral installer"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  Refresh-Path
  if (-not (Has-Command "uv")) {
    throw "uv still was not found after installation. Open a new PowerShell window and retry."
  }
}

function Ensure-Node {
  Refresh-Path
  if ((Has-Command "node") -and (Has-Command "npm")) {
    Write-Host "Node.js is available: $(node --version)"
    Write-Host "npm is available: $(npm --version)"
    return
  }
  if (-not $cfg.install_tools) {
    throw "Node.js/npm is missing. Enable dependency installation in the GUI or install Node.js LTS manually."
  }
  Step "Installing Node.js LTS through winget"
  Require-Winget
  winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
  Refresh-Path
  if (-not ((Has-Command "node") -and (Has-Command "npm"))) {
    throw "Node.js/npm still was not found after installation. Open a new PowerShell window and retry."
  }
}

function Ensure-Ollama {
  Refresh-Path
  if ([string]$cfg.profile -eq "no_model_dev") {
    Write-Host "Skipping Ollama because no_model_dev profile was selected."
    return
  }
  $ollama = Find-Ollama
  if ($ollama) {
    Write-Host "Ollama is available: $ollama"
    return
  }
  if (-not $cfg.install_tools) {
    throw "Ollama is missing. Enable dependency installation in the GUI or install Ollama manually."
  }
  Step "Downloading official Ollama Windows installer"
  $downloadDir = Join-Path $ProjectRoot ".deploy\gui\downloads"
  New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
  $installer = Join-Path $downloadDir "OllamaSetup.exe"
  Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $installer
  Step "Running Ollama installer"
  Start-Process -FilePath $installer -Wait
  Refresh-Path
  $ollama = Find-Ollama
  if (-not $ollama) {
    throw "Ollama still was not found after installation. Finish the Ollama installer, then retry."
  }
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType File -Force -Path $Path | Out-Null
  }
  $lines = @(Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)
  $escaped = [regex]::Escape($Key)
  $found = $false
  $newLines = foreach ($line in $lines) {
    if ($line -match "^\s*$escaped\s*=") {
      $found = $true
      "$Key=$Value"
    } else {
      $line
    }
  }
  if (-not $found) {
    $newLines += "$Key=$Value"
  }
  Set-Content -LiteralPath $Path -Value $newLines -Encoding utf8
}

function Wait-HttpOk([string]$Uri, [int]$TimeoutSeconds = 90) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        return $true
      }
    } catch {
    }
    Start-Sleep -Seconds 2
  }
  return $false
}

function Get-ProfileModels([string]$Profile) {
  $path = Join-Path $ProjectRoot "configs\deployment_profiles\$Profile.json"
  if (-not (Test-Path -LiteralPath $path)) {
    throw "Deployment profile not found: $path"
  }
  $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
  return @($data.models)
}

if ($cfg.download_project) {
  Download-ProjectSource
}
if (-not (Test-ProjectDirectory $ProjectRoot)) {
  throw "Project files are not present at $ProjectRoot."
}
Set-Location -LiteralPath $ProjectRoot

$profileId = [string]$cfg.profile

Step "Checking and installing required tools"
Ensure-Uv
Ensure-Node
Ensure-Ollama

Step "Writing local deployment configuration"
& uv run python scripts/deploy/portable_deploy.py --mode local_lan --profile $profileId --non-interactive
if ($LASTEXITCODE -ne 0) { throw "portable_deploy.py failed." }

$envPath = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
  Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.windows.example") -Destination $envPath
}
Set-DotEnvValue $envPath "PERSONA_RAG_ENV" ([string]$cfg.persona_env)
Set-DotEnvValue $envPath "PERSONA_RAG_HOST" "127.0.0.1"
Set-DotEnvValue $envPath "PERSONA_RAG_PORT" ([string]$cfg.backend_port)
Set-DotEnvValue $envPath "PERSONA_RAG_SQLITE_PATH" ([string]$cfg.sqlite_path)
Set-DotEnvValue $envPath "PERSONA_RAG_OLLAMA_BASE_URL" ([string]$cfg.ollama_base_url)
Set-DotEnvValue $envPath "VITE_API_BASE_URL" "http://127.0.0.1:$($cfg.backend_port)"
Set-DotEnvValue $envPath "PERSONA_RAG_AUTH_REQUIRED" ([string]$cfg.auth_required).ToLowerInvariant()
Set-DotEnvValue $envPath "PERSONA_RAG_AUTH_ADMIN_USERNAME" ([string]$cfg.admin_username)
Set-DotEnvValue $envPath "PERSONA_RAG_AUTH_ADMIN_EMAIL" ([string]$cfg.admin_email)
Set-DotEnvValue $envPath "PERSONA_RAG_AUTH_ADMIN_PASSWORD" ([string]$cfg.admin_password)
Set-DotEnvValue $envPath "PERSONA_RAG_DEEPSEEK_API_KEY" ([string]$cfg.deepseek_api_key)
Set-DotEnvValue $envPath "PERSONA_RAG_SMTP_HOST" ([string]$cfg.smtp_host)
Set-DotEnvValue $envPath "PERSONA_RAG_SMTP_USERNAME" ([string]$cfg.smtp_username)
Set-DotEnvValue $envPath "PERSONA_RAG_SMTP_PASSWORD" ([string]$cfg.smtp_password)
Set-DotEnvValue $envPath "PERSONA_RAG_SMTP_FROM" ([string]$cfg.smtp_from)
Set-DotEnvValue $envPath "PERSONA_RAG_DEPLOYMENT_MODE" "local_lan"
Set-DotEnvValue $envPath "PERSONA_RAG_DEPLOYMENT_PROFILE" $profileId

if ($cfg.install_project_dependencies) {
  Step "Installing backend and frontend dependencies"
  & powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\bootstrap_windows.ps1
  if ($LASTEXITCODE -ne 0) { throw "bootstrap_windows.ps1 failed." }
}

$models = Get-ProfileModels $profileId
if ($cfg.pull_models -and $models.Count -gt 0) {
  Step "Pulling local models: $($models -join ', ')"
  & powershell -NoProfile -ExecutionPolicy Bypass -File scripts\models\pull_required_models.ps1 -Models $models
  if ($LASTEXITCODE -ne 0) { throw "pull_required_models.ps1 failed." }
} elseif ($models.Count -eq 0) {
  Write-Host "No model pull is needed for this profile."
} else {
  Write-Host "Skipping model pull because the GUI option is disabled."
}

if ($cfg.start_app) {
  Step "Starting local backend and frontend"
  & powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\start_all_windows.ps1 `
    -HostAddress "127.0.0.1" `
    -BackendPort ([int]$cfg.backend_port) `
    -FrontendPort ([int]$cfg.frontend_port)
  if ($LASTEXITCODE -ne 0) { throw "start_all_windows.ps1 failed." }

  $frontendUrl = "http://127.0.0.1:$($cfg.frontend_port)"
  Step "Waiting for local browser endpoint: $frontendUrl"
  if (-not (Wait-HttpOk $frontendUrl 120)) {
    throw "Frontend did not become reachable at $frontendUrl."
  }
  if ($cfg.open_browser) {
    Start-Process $frontendUrl
  }
  Write-Host ""
  Write-Host "Local deployment is ready."
  Write-Host "URL: $frontendUrl"
  Write-Host "Login username: $($cfg.admin_username)"
  Write-Host "Login password: $($cfg.admin_password)"
} else {
  Write-Host "Setup completed. Start the app later with scripts\dev\start_all_windows.ps1."
}
'@
  Set-Content -LiteralPath $Path -Value $runner -Encoding utf8
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "Web虚拟分身 Windows 本地快速部署"
$form.StartPosition = "CenterScreen"
$form.Size = New-Object System.Drawing.Size(980, 860)
$form.MinimumSize = New-Object System.Drawing.Size(940, 780)

$title = New-Object System.Windows.Forms.Label
$title.Text = "Web虚拟分身 本地部署向导"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 15, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(20, 16)
$title.Size = New-Object System.Drawing.Size(560, 32)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "一行命令只启动这个小向导；选择安装目录和配置后，向导再下载主项目并启动本地浏览器。"
$subtitle.Location = New-Object System.Drawing.Point(22, 52)
$subtitle.Size = New-Object System.Drawing.Size(880, 24)
$form.Controls.Add($subtitle)

$sourceGroup = New-Object System.Windows.Forms.GroupBox
$sourceGroup.Text = "项目来源与安装位置"
$sourceGroup.Location = New-Object System.Drawing.Point(20, 84)
$sourceGroup.Size = New-Object System.Drawing.Size(920, 140)
$form.Controls.Add($sourceGroup)

$sourceGroup.Controls.Add((New-Label "安装目录" 18 30 90))
$projectText = New-Object System.Windows.Forms.TextBox
$projectText.Location = New-Object System.Drawing.Point(110, 26)
$projectText.Size = New-Object System.Drawing.Size(630, 24)
$projectText.Text = $ProjectRoot
$sourceGroup.Controls.Add($projectText)

$browseButton = New-Object System.Windows.Forms.Button
$browseButton.Text = "选择..."
$browseButton.Location = New-Object System.Drawing.Point(750, 24)
$browseButton.Size = New-Object System.Drawing.Size(70, 28)
$browseButton.Add_Click({
  $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
  $dialog.Description = "选择 Web虚拟分身 安装目录"
  $dialog.SelectedPath = $projectText.Text
  if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    $projectText.Text = $dialog.SelectedPath
  }
})
$sourceGroup.Controls.Add($browseButton)

$openFolderButton = New-Object System.Windows.Forms.Button
$openFolderButton.Text = "打开"
$openFolderButton.Location = New-Object System.Drawing.Point(828, 24)
$openFolderButton.Size = New-Object System.Drawing.Size(70, 28)
$openFolderButton.Add_Click({
  if (Test-Path -LiteralPath $projectText.Text) { Start-Process $projectText.Text }
})
$sourceGroup.Controls.Add($openFolderButton)

$sourceGroup.Controls.Add((New-Label "仓库" 18 64 90))
$repoText = New-Object System.Windows.Forms.TextBox
$repoText.Location = New-Object System.Drawing.Point(110, 60)
$repoText.Size = New-Object System.Drawing.Size(280, 24)
$repoText.Text = $Repo
$sourceGroup.Controls.Add($repoText)

$sourceGroup.Controls.Add((New-Label "分支" 410 64 50))
$branchText = New-Object System.Windows.Forms.TextBox
$branchText.Location = New-Object System.Drawing.Point(462, 60)
$branchText.Size = New-Object System.Drawing.Size(130, 24)
$branchText.Text = $Branch
$sourceGroup.Controls.Add($branchText)

$downloadProject = New-CheckBox "下载/更新主项目代码（如果目录里已有项目且不覆盖，会直接复用）" 110 96 $true 500
$replaceExisting = New-CheckBox "覆盖已有安装目录（会删除该目录后重新下载）" 620 96 ([bool]$Replace) 280
$sourceGroup.Controls.AddRange(@($downloadProject, $replaceExisting))

$runtimeGroup = New-Object System.Windows.Forms.GroupBox
$runtimeGroup.Text = "运行配置"
$runtimeGroup.Location = New-Object System.Drawing.Point(20, 234)
$runtimeGroup.Size = New-Object System.Drawing.Size(920, 190)
$form.Controls.Add($runtimeGroup)

$runtimeGroup.Controls.Add((New-Label "模型配置" 18 32 90))
$profileCombo = New-Object System.Windows.Forms.ComboBox
$profileCombo.Location = New-Object System.Drawing.Point(110, 28)
$profileCombo.Size = New-Object System.Drawing.Size(420, 28)
$profileCombo.DropDownStyle = "DropDownList"
$profiles = @(
  [pscustomobject]@{ Id = "quick_gpu"; Text = "快速体验：Qwen3 0.6B（下载小，先跑通）" },
  [pscustomobject]@{ Id = "standard_gpu"; Text = "标准 GPU：Qwen3.5 9B + embedding（推荐 12GB+ 显存）" },
  [pscustomobject]@{ Id = "minimal_cpu"; Text = "低资源/CPU：Qwen3 8B（可能较慢）" },
  [pscustomobject]@{ Id = "no_model_dev"; Text = "无模型开发：只装依赖和启动界面/API" }
)
$profileCombo.DataSource = $profiles
$profileCombo.DisplayMember = "Text"
$profileCombo.ValueMember = "Id"
$profileCombo.SelectedValue = "quick_gpu"
$runtimeGroup.Controls.Add($profileCombo)

$runtimeGroup.Controls.Add((New-Label "后端端口" 560 32 80))
$backendPort = New-Object System.Windows.Forms.NumericUpDown
$backendPort.Location = New-Object System.Drawing.Point(640, 28)
$backendPort.Minimum = 1024
$backendPort.Maximum = 65535
$backendPort.Value = 8000
$runtimeGroup.Controls.Add($backendPort)

$runtimeGroup.Controls.Add((New-Label "前端端口" 740 32 80))
$frontendPort = New-Object System.Windows.Forms.NumericUpDown
$frontendPort.Location = New-Object System.Drawing.Point(820, 28)
$frontendPort.Minimum = 1024
$frontendPort.Maximum = 65535
$frontendPort.Value = 5173
$runtimeGroup.Controls.Add($frontendPort)

$runtimeGroup.Controls.Add((New-Label "管理员用户" 18 70 90))
$adminUser = New-Object System.Windows.Forms.TextBox
$adminUser.Location = New-Object System.Drawing.Point(110, 66)
$adminUser.Size = New-Object System.Drawing.Size(160, 24)
$adminUser.Text = "admin"
$runtimeGroup.Controls.Add($adminUser)

$runtimeGroup.Controls.Add((New-Label "管理员邮箱" 290 70 90))
$adminEmail = New-Object System.Windows.Forms.TextBox
$adminEmail.Location = New-Object System.Drawing.Point(380, 66)
$adminEmail.Size = New-Object System.Drawing.Size(220, 24)
$adminEmail.Text = "admin@local.persona-rag"
$runtimeGroup.Controls.Add($adminEmail)

$runtimeGroup.Controls.Add((New-Label "管理员密码" 620 70 90))
$adminPassword = New-Object System.Windows.Forms.TextBox
$adminPassword.Location = New-Object System.Drawing.Point(710, 66)
$adminPassword.Size = New-Object System.Drawing.Size(170, 24)
$adminPassword.Text = "admin123456"
$runtimeGroup.Controls.Add($adminPassword)

$authRequired = New-CheckBox "启用登录认证" 110 104 $true 160
$installTools = New-CheckBox "自动安装缺失工具：uv、Node.js/npm、Ollama" 280 104 $true 320
$installProjectDeps = New-CheckBox "安装项目依赖" 610 104 $true 140
$pullModels = New-CheckBox "拉取所选模型" 760 104 $true 130
$startApp = New-CheckBox "完成后启动服务" 110 136 $true 160
$openBrowser = New-CheckBox "启动后打开浏览器" 280 136 $true 180
$runtimeGroup.Controls.AddRange(@($authRequired, $installTools, $installProjectDeps, $pullModels, $startApp, $openBrowser))

$advancedGroup = New-Object System.Windows.Forms.GroupBox
$advancedGroup.Text = "高级配置（可留空）"
$advancedGroup.Location = New-Object System.Drawing.Point(20, 434)
$advancedGroup.Size = New-Object System.Drawing.Size(920, 145)
$form.Controls.Add($advancedGroup)

$advancedGroup.Controls.Add((New-Label "Ollama URL" 18 30 90))
$ollamaUrl = New-Object System.Windows.Forms.TextBox
$ollamaUrl.Location = New-Object System.Drawing.Point(110, 26)
$ollamaUrl.Size = New-Object System.Drawing.Size(220, 24)
$ollamaUrl.Text = "http://127.0.0.1:11434"
$advancedGroup.Controls.Add($ollamaUrl)

$advancedGroup.Controls.Add((New-Label "SQLite 路径" 350 30 80))
$sqlitePath = New-Object System.Windows.Forms.TextBox
$sqlitePath.Location = New-Object System.Drawing.Point(430, 26)
$sqlitePath.Size = New-Object System.Drawing.Size(180, 24)
$sqlitePath.Text = "data/sqlite/persona_rag.sqlite3"
$advancedGroup.Controls.Add($sqlitePath)

$advancedGroup.Controls.Add((New-Label "运行环境" 630 30 70))
$envCombo = New-Object System.Windows.Forms.ComboBox
$envCombo.Location = New-Object System.Drawing.Point(700, 26)
$envCombo.Size = New-Object System.Drawing.Size(120, 24)
$envCombo.DropDownStyle = "DropDownList"
[void]$envCombo.Items.Add("dev")
[void]$envCombo.Items.Add("prod")
$envCombo.SelectedItem = "dev"
$advancedGroup.Controls.Add($envCombo)

$advancedGroup.Controls.Add((New-Label "DeepSeek Key" 18 66 90))
$deepseekKey = New-Object System.Windows.Forms.TextBox
$deepseekKey.Location = New-Object System.Drawing.Point(110, 62)
$deepseekKey.Size = New-Object System.Drawing.Size(300, 24)
$deepseekKey.UseSystemPasswordChar = $true
$advancedGroup.Controls.Add($deepseekKey)

$advancedGroup.Controls.Add((New-Label "SMTP Host" 430 66 80))
$smtpHost = New-Object System.Windows.Forms.TextBox
$smtpHost.Location = New-Object System.Drawing.Point(510, 62)
$smtpHost.Size = New-Object System.Drawing.Size(160, 24)
$advancedGroup.Controls.Add($smtpHost)

$advancedGroup.Controls.Add((New-Label "SMTP User" 690 66 80))
$smtpUser = New-Object System.Windows.Forms.TextBox
$smtpUser.Location = New-Object System.Drawing.Point(770, 62)
$smtpUser.Size = New-Object System.Drawing.Size(120, 24)
$advancedGroup.Controls.Add($smtpUser)

$advancedGroup.Controls.Add((New-Label "SMTP From" 18 102 90))
$smtpFrom = New-Object System.Windows.Forms.TextBox
$smtpFrom.Location = New-Object System.Drawing.Point(110, 98)
$smtpFrom.Size = New-Object System.Drawing.Size(220, 24)
$advancedGroup.Controls.Add($smtpFrom)

$advancedGroup.Controls.Add((New-Label "SMTP 密码" 350 102 80))
$smtpPassword = New-Object System.Windows.Forms.TextBox
$smtpPassword.Location = New-Object System.Drawing.Point(430, 98)
$smtpPassword.Size = New-Object System.Drawing.Size(180, 24)
$smtpPassword.UseSystemPasswordChar = $true
$advancedGroup.Controls.Add($smtpPassword)

$startButton = New-Object System.Windows.Forms.Button
$startButton.Text = "开始部署"
$startButton.Location = New-Object System.Drawing.Point(130, 594)
$startButton.Size = New-Object System.Drawing.Size(120, 34)
$form.Controls.Add($startButton)

$stopButton = New-Object System.Windows.Forms.Button
$stopButton.Text = "停止当前步骤"
$stopButton.Location = New-Object System.Drawing.Point(266, 594)
$stopButton.Size = New-Object System.Drawing.Size(120, 34)
$stopButton.Enabled = $false
$form.Controls.Add($stopButton)

$openLogButton = New-Object System.Windows.Forms.Button
$openLogButton.Text = "打开日志目录"
$openLogButton.Location = New-Object System.Drawing.Point(402, 594)
$openLogButton.Size = New-Object System.Drawing.Size(120, 34)
$form.Controls.Add($openLogButton)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "状态：等待开始"
$statusLabel.Location = New-Object System.Drawing.Point(542, 602)
$statusLabel.Size = New-Object System.Drawing.Size(380, 24)
$form.Controls.Add($statusLabel)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Location = New-Object System.Drawing.Point(20, 640)
$progress.Size = New-Object System.Drawing.Size(920, 16)
$progress.Style = "Blocks"
$form.Controls.Add($progress)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 672)
$logBox.Size = New-Object System.Drawing.Size(920, 125)
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.Font = New-Object System.Drawing.Font("Consolas", 9)
$form.Controls.Add($logBox)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "提示：首次体验建议 quick_gpu。安装目录、仓库分支、端口、账号、模型和可选密钥都可在本窗口修改。"
$hint.Location = New-Object System.Drawing.Point(20, 804)
$hint.Size = New-Object System.Drawing.Size(900, 24)
$form.Controls.Add($hint)

$script:RunnerProcess = $null
$script:LastLogLength = 0
$script:CurrentLogDir = ""
$script:CurrentOutLog = ""
$script:CurrentErrLog = ""

function Read-CombinedLog {
  $parts = @()
  foreach ($path in @($script:CurrentOutLog, $script:CurrentErrLog)) {
    if ($path -and (Test-Path -LiteralPath $path)) {
      try {
        $parts += Get-Content -LiteralPath $path -Raw -ErrorAction Stop
      } catch {
      }
    }
  }
  return ($parts -join "`r`n")
}

$openLogButton.Add_Click({
  if ($script:CurrentLogDir -and (Test-Path -LiteralPath $script:CurrentLogDir)) {
    Start-Process $script:CurrentLogDir
  } else {
    $candidate = Join-Path $projectText.Text ".deploy\gui\logs"
    if (Test-Path -LiteralPath $candidate) { Start-Process $candidate }
  }
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1000
$timer.Add_Tick({
  $text = Read-CombinedLog
  if ($text.Length -ne $script:LastLogLength) {
    $script:LastLogLength = $text.Length
    $logBox.Text = $text
    $logBox.SelectionStart = $logBox.Text.Length
    $logBox.ScrollToCaret()
  }

  if ($script:RunnerProcess -and $script:RunnerProcess.HasExited) {
    $exitCode = $script:RunnerProcess.ExitCode
    $script:RunnerProcess = $null
    $timer.Stop()
    $progress.Style = "Blocks"
    $stopButton.Enabled = $false
    $startButton.Enabled = $true
    if ($exitCode -eq 0) {
      $statusLabel.Text = "状态：部署完成"
      [System.Windows.Forms.MessageBox]::Show(
        "本地部署完成。浏览器地址：http://127.0.0.1:$($frontendPort.Value)`n登录用户：$($adminUser.Text)`n登录密码：$($adminPassword.Text)",
        "Web虚拟分身",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
      ) | Out-Null
    } else {
      $statusLabel.Text = "状态：部署失败，查看日志"
      [System.Windows.Forms.MessageBox]::Show(
        "部署流程退出码：$exitCode。请查看下方日志或日志目录。",
        "Web虚拟分身",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
      ) | Out-Null
    }
  }
})

$startButton.Add_Click({
  $installDir = $projectText.Text.Trim()
  if (-not $installDir) {
    [System.Windows.Forms.MessageBox]::Show("请先选择安装目录。", "Web虚拟分身") | Out-Null
    return
  }
  if ($adminUser.Text.Trim().Length -lt 2 -or $adminUser.Text -match "\s") {
    [System.Windows.Forms.MessageBox]::Show("管理员用户名至少 2 位，且不要包含空白字符。", "Web虚拟分身") | Out-Null
    return
  }
  if ($authRequired.Checked -and ($adminPassword.Text.Trim().Length -lt 8 -or $adminPassword.Text -match "\s")) {
    [System.Windows.Forms.MessageBox]::Show("管理员密码至少 8 位，且不要包含空白字符。", "Web虚拟分身") | Out-Null
    return
  }
  if ($backendPort.Value -eq $frontendPort.Value) {
    [System.Windows.Forms.MessageBox]::Show("后端端口和前端端口不能相同。", "Web虚拟分身") | Out-Null
    return
  }

  # Keep the bootstrap runner outside the target install directory. This prevents the
  # "empty directory" check from seeing our own logs, and it also allows replace-existing
  # installs to delete and recreate the target safely.
  $stateDir = Join-Path ([System.IO.Path]::GetTempPath()) ("web-avatar-gui-state-" + [System.Guid]::NewGuid().ToString("N"))
  $logDir = Join-Path $stateDir "logs"
  New-Item -ItemType Directory -Force -Path $stateDir, $logDir | Out-Null
  $configPath = Join-Path $stateDir "local_gui_config.json"
  $runnerPath = Join-Path $stateDir "local_gui_runner.ps1"
  $script:CurrentLogDir = $logDir
  $script:CurrentOutLog = Join-Path $logDir "local_gui_runner.out.log"
  $script:CurrentErrLog = Join-Path $logDir "local_gui_runner.err.log"
  Write-RunnerScript -Path $runnerPath
  Remove-Item -LiteralPath $script:CurrentOutLog, $script:CurrentErrLog -Force -ErrorAction SilentlyContinue

  $config = [ordered]@{
    project_root = $installDir
    repo = $repoText.Text.Trim()
    branch = $branchText.Text.Trim()
    download_project = [bool]$downloadProject.Checked
    replace_existing = [bool]$replaceExisting.Checked
    profile = [string]$profileCombo.SelectedValue
    persona_env = [string]$envCombo.SelectedItem
    admin_username = $adminUser.Text.Trim()
    admin_email = $adminEmail.Text.Trim()
    admin_password = $adminPassword.Text.Trim()
    auth_required = [bool]$authRequired.Checked
    backend_port = [int]$backendPort.Value
    frontend_port = [int]$frontendPort.Value
    ollama_base_url = $ollamaUrl.Text.Trim()
    sqlite_path = $sqlitePath.Text.Trim()
    deepseek_api_key = $deepseekKey.Text.Trim()
    smtp_host = $smtpHost.Text.Trim()
    smtp_username = $smtpUser.Text.Trim()
    smtp_password = $smtpPassword.Text.Trim()
    smtp_from = $smtpFrom.Text.Trim()
    install_tools = [bool]$installTools.Checked
    install_project_dependencies = [bool]$installProjectDeps.Checked
    pull_models = [bool]$pullModels.Checked
    start_app = [bool]$startApp.Checked
    open_browser = [bool]$openBrowser.Checked
  }
  $config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configPath -Encoding utf8

  $statusLabel.Text = "状态：部署进行中"
  $progress.Style = "Marquee"
  $startButton.Enabled = $false
  $stopButton.Enabled = $true
  $logBox.Text = ""
  $script:LastLogLength = 0

  $args = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`" -ConfigPath `"$configPath`""
  $script:RunnerProcess = Start-Process -FilePath "powershell.exe" `
    -ArgumentList $args `
    -WorkingDirectory $stateDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $script:CurrentOutLog `
    -RedirectStandardError $script:CurrentErrLog `
    -PassThru
  $timer.Start()
})

$stopButton.Add_Click({
  if ($script:RunnerProcess -and -not $script:RunnerProcess.HasExited) {
    try {
      Stop-Process -Id $script:RunnerProcess.Id -Force
    } catch {
    }
  }
  $statusLabel.Text = "状态：已请求停止"
})

$form.Add_FormClosing({
  if ($script:RunnerProcess -and -not $script:RunnerProcess.HasExited) {
    $answer = [System.Windows.Forms.MessageBox]::Show(
      "部署流程仍在运行。确定要关闭窗口并停止当前步骤吗？",
      "Web虚拟分身",
      [System.Windows.Forms.MessageBoxButtons]::YesNo,
      [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
      $_.Cancel = $true
      return
    }
    try { Stop-Process -Id $script:RunnerProcess.Id -Force } catch {}
  }
})

[void]$form.ShowDialog()

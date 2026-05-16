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

try {
  Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class WebVirtualPersonaDpi {
  [DllImport("user32.dll")]
  public static extern bool SetProcessDPIAware();
}
"@ -ErrorAction SilentlyContinue
  [void][WebVirtualPersonaDpi]::SetProcessDPIAware()
} catch {
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
[System.Windows.Forms.Application]::EnableVisualStyles()

function Test-ProjectDirectory([string]$Path) {
  return (Test-Path -LiteralPath (Join-Path $Path "pyproject.toml")) -and
    (Test-Path -LiteralPath (Join-Path $Path "app\frontend\package.json")) -and
    (Test-Path -LiteralPath (Join-Path $Path "scripts\deploy"))
}

function New-Label([string]$Text, [int]$X, [int]$Y, [int]$W = 160, [int]$H = 30) {
  $label = New-Object System.Windows.Forms.Label
  $label.Text = $Text
  $label.Location = New-Object System.Drawing.Point($X, $Y)
  $label.Size = New-Object System.Drawing.Size($W, $H)
  $label.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
  $label.AutoEllipsis = $true
  return $label
}

function New-AutoLabel([string]$Text, [int]$X, [int]$Y) {
  $label = New-Object System.Windows.Forms.Label
  $label.Text = $Text
  $label.Location = New-Object System.Drawing.Point($X, $Y)
  $label.AutoSize = $true
  $label.AutoEllipsis = $false
  return $label
}

function New-CheckBox([string]$Text, [int]$X, [int]$Y, [bool]$Checked = $true, [int]$W = 520) {
  $box = New-Object System.Windows.Forms.CheckBox
  $box.Text = $Text
  $box.Location = New-Object System.Drawing.Point($X, $Y)
  $box.Size = New-Object System.Drawing.Size($W, 32)
  $box.Checked = $Checked
  return $box
}

function Get-PowerShellExecutable {
  $candidates = @()
  if ($PSHOME) {
    $candidates += (Join-Path $PSHOME "powershell.exe")
    $candidates += (Join-Path $PSHOME "pwsh.exe")
  }
  try {
    $currentProcess = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    if ($currentProcess) { $candidates += $currentProcess }
  } catch {
  }
  if ($env:SystemRoot) {
    $candidates += (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe")
    $candidates += (Join-Path $env:SystemRoot "Sysnative\WindowsPowerShell\v1.0\powershell.exe")
    $candidates += (Join-Path $env:SystemRoot "SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
  }
  foreach ($name in @("powershell.exe", "powershell", "pwsh.exe", "pwsh")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
  }
  foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  throw "找不到 PowerShell 可执行文件。请确认 Windows PowerShell 5.1 可用，或修复 PATH 后重试。"
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

function Get-PowerShellExecutable {
  $candidates = @()
  if ($PSHOME) {
    $candidates += (Join-Path $PSHOME "powershell.exe")
    $candidates += (Join-Path $PSHOME "pwsh.exe")
  }
  try {
    $currentProcess = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    if ($currentProcess) { $candidates += $currentProcess }
  } catch {
  }
  if ($env:SystemRoot) {
    $candidates += (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe")
    $candidates += (Join-Path $env:SystemRoot "Sysnative\WindowsPowerShell\v1.0\powershell.exe")
    $candidates += (Join-Path $env:SystemRoot "SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
  }
  foreach ($name in @("powershell.exe", "powershell", "pwsh.exe", "pwsh")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
  }
  foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  throw "找不到 PowerShell 可执行文件。请确认 Windows PowerShell 5.1 可用，或修复 PATH 后重试。"
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

function Ensure-ParentDirectory([string]$Path) {
  $parent = Split-Path -Parent $Path
  if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
  }
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
      Ensure-ParentDirectory $ProjectRoot
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

function Get-CommandSourceSafe([string]$Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Get-DependencySnapshot {
  return [ordered]@{
    uv = Get-CommandSourceSafe "uv"
    node = Get-CommandSourceSafe "node"
    npm = Get-CommandSourceSafe "npm"
    ollama = Find-Ollama
  }
}

function New-DependencyManifest($Before, $After) {
  $uvBefore = [bool]$Before.uv
  $nodeCompleteBefore = ([bool]$Before.node -and [bool]$Before.npm)
  $nodeAbsentBefore = (-not [bool]$Before.node -and -not [bool]$Before.npm)
  $ollamaBefore = [bool]$Before.ollama
  return [ordered]@{
    uv = [ordered]@{
      label = "uv"
      was_present_before = $uvBefore
      before_path = [string]$Before.uv
      after_path = [string]$After.uv
      installed_by_deployer = (-not $uvBefore -and [bool]$After.uv)
      uninstall_kind = "remove_uv_user_bin"
    }
    node = [ordered]@{
      label = "Node.js LTS"
      was_present_before = $nodeCompleteBefore
      before_path = [string]$Before.node
      before_npm_path = [string]$Before.npm
      after_path = [string]$After.node
      after_npm_path = [string]$After.npm
      installed_by_deployer = ($nodeAbsentBefore -and [bool]$After.node -and [bool]$After.npm)
      uninstall_kind = "winget"
      winget_id = "OpenJS.NodeJS.LTS"
    }
    ollama = [ordered]@{
      label = "Ollama"
      was_present_before = $ollamaBefore
      before_path = [string]$Before.ollama
      after_path = [string]$After.ollama
      installed_by_deployer = (-not $ollamaBefore -and [bool]$After.ollama)
      uninstall_kind = "registry_or_winget"
      winget_id = "Ollama.Ollama"
    }
  }
}

function Write-Utf8BomFile([string]$SourcePath, [string]$DestinationPath) {
  $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
  $text = [System.IO.File]::ReadAllText($SourcePath, $strictUtf8).TrimStart([char]0xFEFF)
  $utf8Bom = New-Object System.Text.UTF8Encoding($true)
  [System.IO.File]::WriteAllText($DestinationPath, $text, $utf8Bom)
}

function Save-RemoteUtf8Script([string]$Url, [string]$DestinationPath) {
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $client = New-Object System.Net.WebClient
  try {
    $bytes = $client.DownloadData($Url)
  } finally {
    $client.Dispose()
  }
  $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
  $text = $strictUtf8.GetString($bytes).TrimStart([char]0xFEFF)
  $utf8Bom = New-Object System.Text.UTF8Encoding($true)
  [System.IO.File]::WriteAllText($DestinationPath, $text, $utf8Bom)
}

function Write-UninstallLauncherExe([string]$OutputPath) {
  if (Test-Path -LiteralPath $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force
  }
  $source = @"
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

public static class WebVirtualPersonaUninstallLauncher
{
    [STAThread]
    public static void Main()
    {
        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string script = Path.Combine(root, ".deploy", "uninstall", "windows_uninstall.ps1");
            string manifest = Path.Combine(root, ".deploy", "uninstall", "install_manifest.json");
            if (!File.Exists(script))
            {
                MessageBox.Show("找不到卸载脚本：" + script, "Web虚拟分身 卸载", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            string tempDir = Path.Combine(Path.GetTempPath(), "web-avatar-uninstall-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(tempDir);
            string tempScript = Path.Combine(tempDir, "windows_uninstall.ps1");
            File.Copy(script, tempScript, true);

            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = FindPowerShell();
            info.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -File " + Quote(tempScript) + " -ProjectRoot " + Quote(root) + " -ManifestPath " + Quote(manifest);
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            Process.Start(info);
        }
        catch (Exception ex)
        {
            MessageBox.Show("无法启动卸载程序：" + ex.Message, "Web虚拟分身 卸载", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static string FindPowerShell()
    {
        string systemRoot = Environment.GetEnvironmentVariable("SystemRoot");
        if (String.IsNullOrEmpty(systemRoot))
        {
            systemRoot = @"C:\Windows";
        }
        string[] candidates = new string[] {
            Path.Combine(systemRoot, @"System32\WindowsPowerShell\v1.0\powershell.exe"),
            Path.Combine(systemRoot, @"Sysnative\WindowsPowerShell\v1.0\powershell.exe"),
            Path.Combine(systemRoot, @"SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
        };
        foreach (string candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }
        return "powershell.exe";
    }
}
"@
  Add-Type -TypeDefinition $source `
    -ReferencedAssemblies @("System.Windows.Forms.dll", "System.Drawing.dll") `
    -OutputAssembly $OutputPath `
    -OutputType WindowsApplication `
    -ErrorAction Stop
}

function Write-UninstallerPackage($DependencyManifest) {
  Step "Preparing local uninstaller"
  $uninstallDir = Join-Path $ProjectRoot ".deploy\uninstall"
  New-Item -ItemType Directory -Force -Path $uninstallDir | Out-Null
  $sourceScript = Join-Path $ProjectRoot "scripts\deploy\windows_uninstall.ps1"
  $scriptPath = Join-Path $uninstallDir "windows_uninstall.ps1"
  if (Test-Path -LiteralPath $sourceScript) {
    Write-Utf8BomFile -SourcePath $sourceScript -DestinationPath $scriptPath
  } else {
    $scriptUrl = "https://raw.githubusercontent.com/$Repo/$Branch/scripts/deploy/windows_uninstall.ps1"
    Write-Host "Downloading uninstaller script from $scriptUrl"
    Save-RemoteUtf8Script -Url $scriptUrl -DestinationPath $scriptPath
  }

  $manifestPath = Join-Path $uninstallDir "install_manifest.json"
  $manifest = [ordered]@{
    schema_version = 1
    product = "Web虚拟分身"
    project_root = $ProjectRoot
    repo = $Repo
    branch = $Branch
    profile = [string]$cfg.profile
    installed_at = (Get-Date).ToString("o")
    dependencies = $DependencyManifest
    remove_project_root = $true
  }
  $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8

  $exePath = Join-Path $ProjectRoot "卸载 Web虚拟分身.exe"
  Write-UninstallLauncherExe -OutputPath $exePath
  Write-Host "UNINSTALLER: $exePath"
}

function Ensure-Uv {
  Refresh-Path
  if (Has-Command "uv") {
    Write-Host "uv is available: $((Get-Command uv).Source)"
    return
  }
  if (-not $cfg.install_tools) {
    throw "未检测到 uv。请在图形界面勾选[自动安装 uv / Node / Ollama]，或先手动安装 uv 后重试。"
  }
  Step "Installing uv from official Astral installer"
  $powershell = Get-PowerShellExecutable
  & $powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
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
    throw "未检测到 Node.js/npm。请在图形界面勾选[自动安装 uv / Node / Ollama]，或先手动安装 Node.js LTS 后重试。"
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
    throw "未检测到 Ollama。请在图形界面勾选[自动安装 uv / Node / Ollama]，或先手动安装 Ollama 后重试。"
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

function Write-SuccessMarker([string]$FrontendUrl) {
  $markerDir = Join-Path $ProjectRoot ".deploy\gui"
  New-Item -ItemType Directory -Force -Path $markerDir | Out-Null
  $markerPath = Join-Path $markerDir "last_success.json"
  $marker = [ordered]@{
    ok = $true
    frontend_url = $FrontendUrl
    backend_port = [int]$cfg.backend_port
    frontend_port = [int]$cfg.frontend_port
    admin_username = [string]$cfg.admin_username
    uninstaller_path = (Join-Path $ProjectRoot "卸载 Web虚拟分身.exe")
    completed_at = (Get-Date).ToString("o")
  }
  $marker | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $markerPath -Encoding utf8
  Write-Host "SUCCESS_MARKER: $markerPath"
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
$dependencySnapshotBefore = Get-DependencySnapshot
Ensure-Uv
Ensure-Node
Ensure-Ollama
$dependencySnapshotAfter = Get-DependencySnapshot
$dependencyManifest = New-DependencyManifest $dependencySnapshotBefore $dependencySnapshotAfter

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

Write-UninstallerPackage $dependencyManifest

if ($cfg.install_project_dependencies) {
  Step "Installing backend and frontend dependencies"
  $powershell = Get-PowerShellExecutable
  & $powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\bootstrap_windows.ps1
  if ($LASTEXITCODE -ne 0) { throw "bootstrap_windows.ps1 failed." }
}

$models = Get-ProfileModels $profileId
if ($cfg.pull_models -and $models.Count -gt 0) {
  Step "Pulling local models: $($models -join ', ')"
  $powershell = Get-PowerShellExecutable
  & $powershell -NoProfile -ExecutionPolicy Bypass -File scripts\models\pull_required_models.ps1 -Models $models
  if ($LASTEXITCODE -ne 0) { throw "pull_required_models.ps1 failed." }
} elseif ($models.Count -eq 0) {
  Write-Host "No model pull is needed for this profile."
} else {
  Write-Host "已跳过模型拉取：图形界面中未勾选[拉取所选模型]。"
}

if ($cfg.start_app) {
  Step "Starting local backend and frontend"
  $powershell = Get-PowerShellExecutable
  & $powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\start_all_windows.ps1 `
    -HostAddress "127.0.0.1" `
    -BackendPort ([int]$cfg.backend_port) `
    -FrontendPort ([int]$cfg.frontend_port)
  if ($LASTEXITCODE -ne 0) { throw "start_all_windows.ps1 failed." }

  $frontendUrl = "http://127.0.0.1:$($cfg.frontend_port)"
  Step "Waiting for local browser endpoint: $frontendUrl"
  if (-not (Wait-HttpOk $frontendUrl 120)) {
    throw "Frontend did not become reachable at $frontendUrl."
  }
  try {
    Write-SuccessMarker -FrontendUrl $frontendUrl
  } catch {
    Write-Warning "Could not write deployment success marker: $($_.Exception.Message)"
  }
  if ($cfg.open_browser) {
    try {
      Start-Process $frontendUrl
    } catch {
      Write-Warning "Could not open browser automatically: $($_.Exception.Message)"
    }
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
$form.Size = New-Object System.Drawing.Size(980, 980)
$form.MinimumSize = New-Object System.Drawing.Size(900, 680)
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)

$contentPanel = New-Object System.Windows.Forms.Panel
$contentPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$contentPanel.AutoScroll = $true
$contentPanel.AutoScrollMinSize = New-Object System.Drawing.Size(0, 1280)
$contentPanel.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 20)
$form.Controls.Add($contentPanel)

$title = New-Object System.Windows.Forms.Label
$title.Text = "Web虚拟分身 本地部署"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 15, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(20, 16)
$title.Size = New-Object System.Drawing.Size(560, 32)
$contentPanel.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "选择安装目录和运行配置，点击[开始部署]后会自动下载项目、安装依赖并启动本地服务。"
$subtitle.Location = New-Object System.Drawing.Point(22, 56)
$subtitle.Size = New-Object System.Drawing.Size(880, 38)
$contentPanel.Controls.Add($subtitle)

$sourceGroup = New-Object System.Windows.Forms.GroupBox
$sourceGroup.Text = "项目来源与安装位置"
$sourceGroup.Location = New-Object System.Drawing.Point(20, 104)
$sourceGroup.Size = New-Object System.Drawing.Size(900, 176)
$contentPanel.Controls.Add($sourceGroup)

$sourceGroup.Controls.Add((New-Label "安装目录" 18 34 90))
$projectText = New-Object System.Windows.Forms.TextBox
$projectText.Location = New-Object System.Drawing.Point(110, 30)
$projectText.Size = New-Object System.Drawing.Size(630, 28)
$projectText.Text = $ProjectRoot
$sourceGroup.Controls.Add($projectText)

$browseButton = New-Object System.Windows.Forms.Button
$browseButton.Text = "选择..."
$browseButton.Location = New-Object System.Drawing.Point(750, 28)
$browseButton.Size = New-Object System.Drawing.Size(70, 32)
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
$openFolderButton.Location = New-Object System.Drawing.Point(828, 28)
$openFolderButton.Size = New-Object System.Drawing.Size(70, 32)
$openFolderButton.Add_Click({
  if (Test-Path -LiteralPath $projectText.Text) { Start-Process $projectText.Text }
})
$sourceGroup.Controls.Add($openFolderButton)

$sourceGroup.Controls.Add((New-Label "仓库" 18 76 90))
$repoText = New-Object System.Windows.Forms.TextBox
$repoText.Location = New-Object System.Drawing.Point(110, 72)
$repoText.Size = New-Object System.Drawing.Size(280, 28)
$repoText.Text = $Repo
$sourceGroup.Controls.Add($repoText)

$sourceGroup.Controls.Add((New-Label "分支" 410 76 50))
$branchText = New-Object System.Windows.Forms.TextBox
$branchText.Location = New-Object System.Drawing.Point(462, 72)
$branchText.Size = New-Object System.Drawing.Size(130, 28)
$branchText.Text = $Branch
$sourceGroup.Controls.Add($branchText)

$downloadProject = New-CheckBox "下载/更新主项目代码（如果目录里已有项目且不覆盖，会直接复用）" 110 106 $true 760
$replaceExisting = New-CheckBox "覆盖已有安装目录（会删除该目录后重新下载）" 110 136 ([bool]$Replace) 760
$sourceGroup.Controls.AddRange(@($downloadProject, $replaceExisting))

$runtimeGroup = New-Object System.Windows.Forms.GroupBox
$runtimeGroup.Text = "运行配置"
$runtimeGroup.Location = New-Object System.Drawing.Point(20, 292)
$runtimeGroup.Size = New-Object System.Drawing.Size(900, 248)
$contentPanel.Controls.Add($runtimeGroup)

$runtimeGroup.Controls.Add((New-Label "模型配置" 18 34 90))
$profileCombo = New-Object System.Windows.Forms.ComboBox
$profileCombo.Location = New-Object System.Drawing.Point(110, 30)
$profileCombo.Size = New-Object System.Drawing.Size(760, 30)
$profileCombo.DropDownWidth = 780
$profileCombo.DropDownStyle = "DropDownList"
$profiles = @(
  [pscustomobject]@{ Id = "quick_gpu"; Text = "快速体验：Qwen3 0.6B（下载小，先跑通）" },
  [pscustomobject]@{ Id = "standard_gpu"; Text = "标准 GPU：Qwen3.5 9B + embedding（推荐 12GB+ 显存）" },
  [pscustomobject]@{ Id = "minimal_cpu"; Text = "低资源/CPU：Qwen3 8B（可能较慢）" },
  [pscustomobject]@{ Id = "no_model_dev"; Text = "无模型开发：只装依赖和启动界面/API" }
)
$profileCombo.Tag = $profiles
foreach ($profile in $profiles) {
  [void]$profileCombo.Items.Add([string]$profile.Text)
}
$profileCombo.SelectedIndex = 0
$runtimeGroup.Controls.Add($profileCombo)

$runtimeGroup.Controls.Add((New-Label "后端" 18 78 48))
$backendPort = New-Object System.Windows.Forms.NumericUpDown
$backendPort.Location = New-Object System.Drawing.Point(74, 74)
$backendPort.Size = New-Object System.Drawing.Size(70, 28)
$backendPort.Minimum = 1024
$backendPort.Maximum = 65535
$backendPort.Value = 8000
$runtimeGroup.Controls.Add($backendPort)

$runtimeGroup.Controls.Add((New-Label "前端" 170 78 48))
$frontendPort = New-Object System.Windows.Forms.NumericUpDown
$frontendPort.Location = New-Object System.Drawing.Point(226, 74)
$frontendPort.Size = New-Object System.Drawing.Size(70, 28)
$frontendPort.Minimum = 1024
$frontendPort.Maximum = 65535
$frontendPort.Value = 5173
$runtimeGroup.Controls.Add($frontendPort)

$runtimeGroup.Controls.Add((New-Label "用户" 322 78 48))
$adminUser = New-Object System.Windows.Forms.TextBox
$adminUser.Location = New-Object System.Drawing.Point(376, 74)
$adminUser.Size = New-Object System.Drawing.Size(145, 28)
$adminUser.Text = "admin"
$runtimeGroup.Controls.Add($adminUser)

$runtimeGroup.Controls.Add((New-Label "邮箱" 18 122 48))
$adminEmail = New-Object System.Windows.Forms.TextBox
$adminEmail.Location = New-Object System.Drawing.Point(74, 118)
$adminEmail.Size = New-Object System.Drawing.Size(316, 28)
$adminEmail.Text = "admin@local.persona-rag"
$runtimeGroup.Controls.Add($adminEmail)

$runtimeGroup.Controls.Add((New-Label "密码" 548 78 48))
$adminPassword = New-Object System.Windows.Forms.TextBox
$adminPassword.Location = New-Object System.Drawing.Point(602, 74)
$adminPassword.Size = New-Object System.Drawing.Size(180, 28)
$adminPassword.Text = "admin123456"
$runtimeGroup.Controls.Add($adminPassword)

$authRequired = New-CheckBox "启用登录认证" 420 118 $true 140
$installTools = New-CheckBox "自动安装 uv / Node / Ollama" 110 160 $true 380
$installProjectDeps = New-CheckBox "安装项目依赖" 510 160 $true 150
$pullModels = New-CheckBox "拉取所选模型" 680 160 $true 160
$startApp = New-CheckBox "完成后启动服务" 110 202 $true 160
$openBrowser = New-CheckBox "启动后打开浏览器" 280 202 $true 180
$runtimeGroup.Controls.AddRange(@($authRequired, $installTools, $installProjectDeps, $pullModels, $startApp, $openBrowser))

$advancedGroup = New-Object System.Windows.Forms.GroupBox
$advancedGroup.Text = "高级配置（可留空）"
$advancedGroup.Location = New-Object System.Drawing.Point(20, 552)
$advancedGroup.Size = New-Object System.Drawing.Size(900, 220)
$contentPanel.Controls.Add($advancedGroup)

$advancedGroup.Controls.Add((New-AutoLabel "Ollama 地址" 18 36))
$ollamaUrl = New-Object System.Windows.Forms.TextBox
$ollamaUrl.Location = New-Object System.Drawing.Point(148, 30)
$ollamaUrl.Size = New-Object System.Drawing.Size(260, 28)
$ollamaUrl.Text = "http://127.0.0.1:11434"
$advancedGroup.Controls.Add($ollamaUrl)

$advancedGroup.Controls.Add((New-AutoLabel "数据路径" 430 36))
$sqlitePath = New-Object System.Windows.Forms.TextBox
$sqlitePath.Location = New-Object System.Drawing.Point(520, 30)
$sqlitePath.Size = New-Object System.Drawing.Size(230, 28)
$sqlitePath.Text = "data/sqlite/persona_rag.sqlite3"
$advancedGroup.Controls.Add($sqlitePath)

$advancedGroup.Controls.Add((New-AutoLabel "环境" 770 36))
$envCombo = New-Object System.Windows.Forms.ComboBox
$envCombo.Location = New-Object System.Drawing.Point(812, 30)
$envCombo.Size = New-Object System.Drawing.Size(76, 28)
$envCombo.DropDownStyle = "DropDownList"
[void]$envCombo.Items.Add("dev")
[void]$envCombo.Items.Add("prod")
$envCombo.SelectedItem = "dev"
$advancedGroup.Controls.Add($envCombo)

$advancedGroup.Controls.Add((New-AutoLabel "DeepSeek 密钥" 18 82))
$deepseekKey = New-Object System.Windows.Forms.TextBox
$deepseekKey.Location = New-Object System.Drawing.Point(148, 76)
$deepseekKey.Size = New-Object System.Drawing.Size(740, 28)
$deepseekKey.UseSystemPasswordChar = $true
$advancedGroup.Controls.Add($deepseekKey)

$advancedGroup.Controls.Add((New-AutoLabel "SMTP 主机" 18 128))
$smtpHost = New-Object System.Windows.Forms.TextBox
$smtpHost.Location = New-Object System.Drawing.Point(148, 122)
$smtpHost.Size = New-Object System.Drawing.Size(260, 28)
$advancedGroup.Controls.Add($smtpHost)

$advancedGroup.Controls.Add((New-AutoLabel "SMTP 用户" 430 128))
$smtpUser = New-Object System.Windows.Forms.TextBox
$smtpUser.Location = New-Object System.Drawing.Point(520, 122)
$smtpUser.Size = New-Object System.Drawing.Size(230, 28)
$advancedGroup.Controls.Add($smtpUser)

$advancedGroup.Controls.Add((New-AutoLabel "SMTP 发件" 18 174))
$smtpFrom = New-Object System.Windows.Forms.TextBox
$smtpFrom.Location = New-Object System.Drawing.Point(148, 168)
$smtpFrom.Size = New-Object System.Drawing.Size(260, 28)
$advancedGroup.Controls.Add($smtpFrom)

$advancedGroup.Controls.Add((New-AutoLabel "SMTP 密码" 430 174))
$smtpPassword = New-Object System.Windows.Forms.TextBox
$smtpPassword.Location = New-Object System.Drawing.Point(520, 168)
$smtpPassword.Size = New-Object System.Drawing.Size(230, 28)
$smtpPassword.UseSystemPasswordChar = $true
$advancedGroup.Controls.Add($smtpPassword)

$startButton = New-Object System.Windows.Forms.Button
$startButton.Text = "开始部署"
$startButton.Location = New-Object System.Drawing.Point(130, 792)
$startButton.Size = New-Object System.Drawing.Size(120, 38)
$contentPanel.Controls.Add($startButton)

$stopButton = New-Object System.Windows.Forms.Button
$stopButton.Text = "停止当前步骤"
$stopButton.Location = New-Object System.Drawing.Point(266, 792)
$stopButton.Size = New-Object System.Drawing.Size(132, 38)
$stopButton.Enabled = $false
$contentPanel.Controls.Add($stopButton)

$openLogButton = New-Object System.Windows.Forms.Button
$openLogButton.Text = "打开日志目录"
$openLogButton.Location = New-Object System.Drawing.Point(414, 792)
$openLogButton.Size = New-Object System.Drawing.Size(150, 38)
$contentPanel.Controls.Add($openLogButton)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "状态：等待开始"
$statusLabel.Location = New-Object System.Drawing.Point(584, 798)
$statusLabel.Size = New-Object System.Drawing.Size(336, 32)
$contentPanel.Controls.Add($statusLabel)

$stageLabel = New-Object System.Windows.Forms.Label
$stageLabel.Text = "当前阶段：等待开始"
$stageLabel.Location = New-Object System.Drawing.Point(20, 840)
$stageLabel.Size = New-Object System.Drawing.Size(500, 30)
$contentPanel.Controls.Add($stageLabel)

$stageCountLabel = New-Object System.Windows.Forms.Label
$stageCountLabel.Text = "总体进度：0/8"
$stageCountLabel.Location = New-Object System.Drawing.Point(542, 840)
$stageCountLabel.Size = New-Object System.Drawing.Size(160, 30)
$contentPanel.Controls.Add($stageCountLabel)

$elapsedLabel = New-Object System.Windows.Forms.Label
$elapsedLabel.Text = "耗时：00:00:00"
$elapsedLabel.Location = New-Object System.Drawing.Point(720, 840)
$elapsedLabel.Size = New-Object System.Drawing.Size(200, 30)
$contentPanel.Controls.Add($elapsedLabel)

$detailLabel = New-Object System.Windows.Forms.Label
$detailLabel.Text = "最近动作：等待开始部署"
$detailLabel.Location = New-Object System.Drawing.Point(20, 874)
$detailLabel.Size = New-Object System.Drawing.Size(900, 30)
$contentPanel.Controls.Add($detailLabel)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Location = New-Object System.Drawing.Point(20, 904)
$progress.Size = New-Object System.Drawing.Size(900, 16)
$progress.Style = "Blocks"
$progress.Minimum = 0
$progress.Maximum = 100
$contentPanel.Controls.Add($progress)

$stagePanel = New-Object System.Windows.Forms.Panel
$stagePanel.Location = New-Object System.Drawing.Point(20, 936)
$stagePanel.Size = New-Object System.Drawing.Size(900, 116)
$stagePanel.BorderStyle = "FixedSingle"
$stagePanel.BackColor = [System.Drawing.SystemColors]::Window
$contentPanel.Controls.Add($stagePanel)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 1068)
$logBox.Size = New-Object System.Drawing.Size(900, 128)
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.Font = New-Object System.Drawing.Font("Consolas", 9)
$contentPanel.Controls.Add($logBox)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "提示：首次体验建议 quick_gpu。安装目录、仓库分支、端口、账号、模型和可选密钥都可在本窗口修改。"
$hint.Location = New-Object System.Drawing.Point(20, 1214)
$hint.Size = New-Object System.Drawing.Size(900, 36)
$contentPanel.Controls.Add($hint)

$script:RunnerProcess = $null
$script:LastLogLength = 0
$script:CurrentLogDir = ""
$script:CurrentOutLog = ""
$script:CurrentErrLog = ""
$script:CurrentStageIndex = -1
$script:DeploymentStartedAt = $null
$script:ProgressStages = @(
  [pscustomobject]@{ Key = "download"; Text = "下载项目源码"; Percent = 10; Pattern = "Downloading project source|Using existing project directory" },
  [pscustomobject]@{ Key = "tools"; Text = "检查/安装工具"; Percent = 25; Pattern = "Checking and installing required tools|Installing uv|Installing Node\.js|Ollama is available|uv is available|Node\.js is available" },
  [pscustomobject]@{ Key = "config"; Text = "写入本地配置"; Percent = 35; Pattern = "Writing local deployment configuration|Preparing local uninstaller|UNINSTALLER:|Updated portable deployment overrides|portable_deploy\.py" },
  [pscustomobject]@{ Key = "deps"; Text = "安装项目依赖"; Percent = 55; Pattern = "Installing backend and frontend dependencies|Bootstrap complete|bootstrap_windows\.ps1" },
  [pscustomobject]@{ Key = "models"; Text = "拉取/确认模型"; Percent = 70; Pattern = "Pulling local models|No model pull is needed|Skipping model pull" },
  [pscustomobject]@{ Key = "start"; Text = "启动本地服务"; Percent = 85; Pattern = "Starting local backend and frontend|start_all_windows\.ps1|Started backend|Started frontend" },
  [pscustomobject]@{ Key = "wait"; Text = "等待浏览器端点"; Percent = 95; Pattern = "Waiting for local browser endpoint" },
  [pscustomobject]@{ Key = "ready"; Text = "部署完成"; Percent = 100; Pattern = "SUCCESS_MARKER:|Local deployment is ready\.|Setup completed\." }
)
$script:StageItemLabels = @()
for ($i = 0; $i -lt $script:ProgressStages.Count; $i++) {
  $stageItem = New-Object System.Windows.Forms.Label
  $stageItem.Location = New-Object System.Drawing.Point((8 + 456 * [Math]::Floor($i / 4)), (8 + 26 * ($i % 4)))
  $stageItem.Size = New-Object System.Drawing.Size(430, 24)
  $stageItem.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8.5)
  $stageItem.Text = ""
  $stagePanel.Controls.Add($stageItem)
  $script:StageItemLabels += $stageItem
}

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

function Format-StageLine([int]$Index) {
  $stage = $script:ProgressStages[$Index]
  if ($Index -lt $script:CurrentStageIndex) {
    $state = "已完成"
  } elseif ($Index -eq $script:CurrentStageIndex) {
    $state = "进行中"
  } else {
    $state = "等待中"
  }
  return ("{0}. [{1}] {2}" -f ($Index + 1), $state, $stage.Text)
}

function Render-ProgressStages {
  for ($i = 0; $i -lt $script:StageItemLabels.Count; $i++) {
    $label = $script:StageItemLabels[$i]
    $label.Text = Format-StageLine $i
    if ($i -lt $script:CurrentStageIndex) {
      $label.ForeColor = [System.Drawing.Color]::FromArgb(35, 120, 65)
    } elseif ($i -eq $script:CurrentStageIndex) {
      $label.ForeColor = [System.Drawing.Color]::FromArgb(25, 90, 170)
    } else {
      $label.ForeColor = [System.Drawing.SystemColors]::GrayText
    }
  }
}

function Reset-ProgressView {
  $script:CurrentStageIndex = -1
  $script:DeploymentStartedAt = $null
  $progress.Style = "Blocks"
  $progress.Value = 0
  $stageLabel.Text = "当前阶段：等待开始"
  $stageCountLabel.Text = "总体进度：0/$($script:ProgressStages.Count)"
  $elapsedLabel.Text = "耗时：00:00:00"
  $detailLabel.Text = "最近动作：等待开始部署"
  Render-ProgressStages
}

function Get-LatestLogDetail([string]$Text) {
  if (-not $Text) { return "等待部署输出..." }
  $normalized = $Text -replace "`r`n", "`n" -replace "`r", "`n"
  $lines = @($normalized -split "`n" | Where-Object { $_.Trim().Length -gt 0 })
  if ($lines.Count -eq 0) { return "等待部署输出..." }
  $line = $lines[-1].Trim()
  if ($line.Length -gt 120) {
    $line = $line.Substring(0, 117) + "..."
  }
  return $line
}

function Set-ProgressStage([int]$Index, [string]$Detail = "") {
  if ($Index -lt 0 -or $Index -ge $script:ProgressStages.Count) { return }
  if ($Index -lt $script:CurrentStageIndex) {
    if ($Detail) { $detailLabel.Text = "最近动作：$Detail" }
    return
  }

  $script:CurrentStageIndex = $Index
  $stage = $script:ProgressStages[$Index]
  $progress.Style = "Blocks"
  $progress.Value = [Math]::Max(0, [Math]::Min(100, [int]$stage.Percent))
  $stageLabel.Text = "当前阶段：$($stage.Text)"
  $stageCountLabel.Text = "总体进度：$($Index + 1)/$($script:ProgressStages.Count)"
  if ($Detail) { $detailLabel.Text = "最近动作：$Detail" }
  Render-ProgressStages
}

function Set-ProgressStageByKey([string]$Key, [string]$Detail = "") {
  for ($i = 0; $i -lt $script:ProgressStages.Count; $i++) {
    if ($script:ProgressStages[$i].Key -eq $Key) {
      Set-ProgressStage $i $Detail
      return
    }
  }
}

function Update-ProgressFromLog([string]$Text) {
  if ($script:DeploymentStartedAt) {
    $elapsed = New-TimeSpan -Start $script:DeploymentStartedAt -End (Get-Date)
    $elapsedLabel.Text = "耗时：{0:hh\:mm\:ss}" -f $elapsed
  }

  if (-not $Text) { return }
  $detail = Get-LatestLogDetail $Text
  $matchedIndex = -1
  for ($i = 0; $i -lt $script:ProgressStages.Count; $i++) {
    if ($Text -match $script:ProgressStages[$i].Pattern) {
      $matchedIndex = $i
    }
  }
  if ($matchedIndex -ge 0) {
    Set-ProgressStage $matchedIndex $detail
  } elseif ($script:CurrentStageIndex -ge 0) {
    $detailLabel.Text = "最近动作：$detail"
  }
}

function Get-SelectedProfileId($ComboBox) {
  if ($ComboBox.Tag -and $ComboBox.SelectedIndex -ge 0) {
    $profiles = @($ComboBox.Tag)
    if ($ComboBox.SelectedIndex -lt $profiles.Count -and ($profiles[$ComboBox.SelectedIndex].PSObject.Properties.Name -contains "Id")) {
      return [string]$profiles[$ComboBox.SelectedIndex].Id
    }
  }
  $selected = $ComboBox.SelectedItem
  if ($selected -and ($selected.PSObject.Properties.Name -contains "Id")) {
    return [string]$selected.Id
  }
  $value = $ComboBox.SelectedValue
  if ($value -and ($value.PSObject.Properties.Name -contains "Id")) {
    return [string]$value.Id
  }
  return [string]$value
}

function Test-GuiDeploymentSucceeded([int]$FrontendPort, [string]$ProjectRoot) {
  if ($ProjectRoot) {
    $markerPath = Join-Path $ProjectRoot ".deploy\gui\last_success.json"
    if (Test-Path -LiteralPath $markerPath) {
      try {
        $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
        if ($marker.ok -or $marker.frontend_url) {
          return $true
        }
      } catch {
        return $true
      }
    }
  }

  $text = Read-CombinedLog
  return ($text -match "SUCCESS_MARKER:" -or $text -match "Local deployment is ready\.")
}

function Show-DeploymentSuccessDialog([string]$FrontendUrl, [string]$Username, [string]$Password, [string]$ProjectRoot) {
  $dialog = New-Object System.Windows.Forms.Form
  $dialog.Text = "部署完成"
  $dialog.StartPosition = "CenterParent"
  $dialog.Size = New-Object System.Drawing.Size(560, 320)
  $dialog.FormBorderStyle = "FixedDialog"
  $dialog.MaximizeBox = $false
  $dialog.MinimizeBox = $false
  $dialog.ShowInTaskbar = $true
  $dialog.TopMost = $true

  $title = New-Object System.Windows.Forms.Label
  $title.Text = "部署完成，可以开始使用了"
  $title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 13, [System.Drawing.FontStyle]::Bold)
  $title.Location = New-Object System.Drawing.Point(24, 22)
  $title.Size = New-Object System.Drawing.Size(500, 30)
  $dialog.Controls.Add($title)

  $urlLabel = New-Label "浏览器地址" 24 72 90
  $dialog.Controls.Add($urlLabel)
  $urlBox = New-Object System.Windows.Forms.TextBox
  $urlBox.Text = $FrontendUrl
  $urlBox.Location = New-Object System.Drawing.Point(120, 68)
  $urlBox.Size = New-Object System.Drawing.Size(390, 24)
  $urlBox.ReadOnly = $true
  $dialog.Controls.Add($urlBox)

  $userLabel = New-Label "登录用户" 24 112 90
  $dialog.Controls.Add($userLabel)
  $userBox = New-Object System.Windows.Forms.TextBox
  $userBox.Text = $Username
  $userBox.Location = New-Object System.Drawing.Point(120, 108)
  $userBox.Size = New-Object System.Drawing.Size(150, 24)
  $userBox.ReadOnly = $true
  $dialog.Controls.Add($userBox)

  $passLabel = New-Label "登录密码" 290 112 90
  $dialog.Controls.Add($passLabel)
  $passBox = New-Object System.Windows.Forms.TextBox
  $passBox.Text = $Password
  $passBox.Location = New-Object System.Drawing.Point(380, 108)
  $passBox.Size = New-Object System.Drawing.Size(130, 24)
  $passBox.ReadOnly = $true
  $dialog.Controls.Add($passBox)

  $note = New-Object System.Windows.Forms.Label
  $note.Text = "部署流程已经完成。安装目录中已生成[卸载 Web虚拟分身.exe]；需要移除本次安装时运行它即可。"
  $note.Location = New-Object System.Drawing.Point(24, 154)
  $note.Size = New-Object System.Drawing.Size(500, 50)
  $dialog.Controls.Add($note)

  $openButton = New-Object System.Windows.Forms.Button
  $openButton.Text = "打开浏览器"
  $openButton.Location = New-Object System.Drawing.Point(120, 230)
  $openButton.Size = New-Object System.Drawing.Size(110, 32)
  $openButton.Add_Click({
    try {
      Start-Process $FrontendUrl
    } catch {
      [System.Windows.Forms.MessageBox]::Show("无法自动打开浏览器：$($_.Exception.Message)", "Web虚拟分身") | Out-Null
    }
  })
  $dialog.Controls.Add($openButton)

  $folderButton = New-Object System.Windows.Forms.Button
  $folderButton.Text = "安装目录"
  $folderButton.Location = New-Object System.Drawing.Point(250, 230)
  $folderButton.Size = New-Object System.Drawing.Size(100, 32)
  $folderButton.Add_Click({
    if ($ProjectRoot -and (Test-Path -LiteralPath $ProjectRoot)) {
      Start-Process $ProjectRoot
    }
  })
  $dialog.Controls.Add($folderButton)

  $okButton = New-Object System.Windows.Forms.Button
  $okButton.Text = "关闭"
  $okButton.Location = New-Object System.Drawing.Point(370, 230)
  $okButton.Size = New-Object System.Drawing.Size(90, 32)
  $okButton.Add_Click({ $dialog.Close() })
  $dialog.Controls.Add($okButton)
  $dialog.AcceptButton = $okButton
  $dialog.CancelButton = $okButton
  $dialog.Add_Shown({
    $dialog.Activate()
    $dialog.TopMost = $true
  })

  [void]$dialog.ShowDialog()
}

function Show-DeploymentSuccessNotice([string]$FrontendUrl, [string]$Username, [string]$Password, [string]$ProjectRoot) {
  try {
    Show-DeploymentSuccessDialog -FrontendUrl $FrontendUrl -Username $Username -Password $Password -ProjectRoot $ProjectRoot
  } catch {
    [System.Windows.Forms.MessageBox]::Show(
      "本地部署完成。浏览器地址：$FrontendUrl`n登录用户：$Username`n登录密码：$Password`n`n成功界面显示失败，已切换到基础提示框：$($_.Exception.Message)",
      "Web虚拟分身",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
  }
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
  Update-ProgressFromLog $text

  if ($script:RunnerProcess -and $script:RunnerProcess.HasExited) {
    $exitCode = $script:RunnerProcess.ExitCode
    $script:RunnerProcess = $null
    $timer.Stop()
    $progress.Style = "Blocks"
    $stopButton.Enabled = $false
    $startButton.Enabled = $true
    $installDirForResult = $projectText.Text.Trim()
    $deploymentSucceeded = ($exitCode -eq 0) -or (Test-GuiDeploymentSucceeded ([int]$frontendPort.Value) $installDirForResult)
    if ($deploymentSucceeded) {
      Set-ProgressStageByKey "ready" "部署完成，已生成本地访问入口。"
      $statusLabel.Text = "状态：部署完成"
      Show-DeploymentSuccessNotice `
        -FrontendUrl "http://127.0.0.1:$($frontendPort.Value)" `
        -Username ($adminUser.Text.Trim()) `
        -Password ($adminPassword.Text.Trim()) `
        -ProjectRoot $installDirForResult
    } else {
      $statusLabel.Text = "状态：部署失败，查看日志"
      $stageLabel.Text = "当前阶段：部署失败"
      $detailLabel.Text = "最近动作：请查看下方错误日志或打开日志目录。"
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
  Remove-Item -LiteralPath (Join-Path $installDir ".deploy\gui\last_success.json") -Force -ErrorAction SilentlyContinue
  $profileIdForConfig = Get-SelectedProfileId $profileCombo

  $config = [ordered]@{
    project_root = $installDir
    repo = $repoText.Text.Trim()
    branch = $branchText.Text.Trim()
    download_project = [bool]$downloadProject.Checked
    replace_existing = [bool]$replaceExisting.Checked
    profile = $profileIdForConfig
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
  Reset-ProgressView
  $script:DeploymentStartedAt = Get-Date
  Set-ProgressStageByKey "download" "准备启动部署 runner。"
  $startButton.Enabled = $false
  $stopButton.Enabled = $true
  $logBox.Text = ""
  $script:LastLogLength = 0

  $powershell = Get-PowerShellExecutable
  $args = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`" -ConfigPath `"$configPath`""
  $script:RunnerProcess = Start-Process -FilePath $powershell `
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
  $stageLabel.Text = "当前阶段：已请求停止"
  $detailLabel.Text = "最近动作：正在停止当前部署 runner。"
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

Reset-ProgressView
[void]$form.ShowDialog()

param(
  [string]$ProjectRoot = "",
  [string]$ManifestPath = "",
  [switch]$AssumeYes
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

function Show-Info([string]$Message) {
  if ($AssumeYes) {
    Write-Host $Message
    return
  }
  [System.Windows.Forms.MessageBox]::Show(
    $Message,
    "Web虚拟分身 卸载",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
  ) | Out-Null
}

function Show-WarningMessage([string]$Message) {
  if ($AssumeYes) {
    Write-Warning $Message
    return
  }
  [System.Windows.Forms.MessageBox]::Show(
    $Message,
    "Web虚拟分身 卸载",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Warning
  ) | Out-Null
}

function Write-UninstallLog([string]$Message) {
  $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  $line = "[$stamp] $Message"
  $script:LogLines += $line
  try {
    Add-Content -LiteralPath $script:LogPath -Value $line -Encoding utf8
  } catch {
  }
}

function Convert-ToFullPath([string]$Path) {
  if (-not $Path) { return "" }
  return [System.IO.Path]::GetFullPath($Path)
}

function Test-ProjectDirectory([string]$Path) {
  return (Test-Path -LiteralPath (Join-Path $Path "pyproject.toml")) -and
    (Test-Path -LiteralPath (Join-Path $Path "app\frontend\package.json")) -and
    (Test-Path -LiteralPath (Join-Path $Path "scripts\deploy"))
}

function Assert-SafeProjectRoot([string]$Path, $Manifest) {
  if (-not $Path) {
    throw "没有找到安装目录。"
  }
  $full = Convert-ToFullPath $Path
  $root = [System.IO.Path]::GetPathRoot($full)
  if (-not $full -or ($full.TrimEnd('\') -eq $root.TrimEnd('\'))) {
    throw "安装目录看起来像磁盘根目录，已停止卸载：$full"
  }
  if ($full.Length -lt 8) {
    throw "安装目录过短，已停止卸载：$full"
  }
  $manifestRoot = ""
  if ($Manifest -and $Manifest.project_root) {
    $manifestRoot = Convert-ToFullPath ([string]$Manifest.project_root)
  }
  if ($manifestRoot -and ($manifestRoot.TrimEnd('\') -ne $full.TrimEnd('\'))) {
    throw "安装清单中的目录与当前目录不一致，已停止卸载。`n当前目录：$full`n清单目录：$manifestRoot"
  }
  if (-not (Test-ProjectDirectory $full)) {
    throw "目标目录不像 Web虚拟分身 安装目录，已停止卸载：$full"
  }
  return $full
}

function Load-Manifest([string]$Path) {
  if ($Path -and (Test-Path -LiteralPath $Path)) {
    try {
      return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    } catch {
      Write-UninstallLog "安装清单读取失败，将只卸载项目目录：$($_.Exception.Message)"
    }
  }
  return $null
}

function Stop-ProjectProcesses([string]$Root) {
  Write-UninstallLog "正在停止安装目录相关的本地服务进程。"
  $escapedRoot = [regex]::Escape($Root)
  $currentPid = $PID
  $stopped = 0
  try {
    $processes = Get-CimInstance Win32_Process -ErrorAction Stop |
      Where-Object {
        $_.ProcessId -ne $currentPid -and
        $_.CommandLine -and
        ($_.CommandLine -match $escapedRoot)
      }
    foreach ($proc in $processes) {
      try {
        Write-UninstallLog "停止进程 PID=$($proc.ProcessId) NAME=$($proc.Name)"
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        $stopped += 1
      } catch {
        Write-UninstallLog "进程停止失败 PID=$($proc.ProcessId)：$($_.Exception.Message)"
      }
    }
  } catch {
    Write-UninstallLog "进程扫描失败：$($_.Exception.Message)"
  }
  Write-UninstallLog "已请求停止 $stopped 个相关进程。"
}

function Should-UninstallDependency($Dependency) {
  if (-not $Dependency) { return $false }
  $installedByDeployer = $false
  $wasPresentBefore = $true
  try { $installedByDeployer = [bool]$Dependency.installed_by_deployer } catch {}
  try { $wasPresentBefore = [bool]$Dependency.was_present_before } catch {}
  return ($installedByDeployer -and -not $wasPresentBefore)
}

function Remove-UvInstalledByDeployer($Dependency) {
  if (-not (Should-UninstallDependency $Dependency)) {
    Write-UninstallLog "保留 uv：部署前已存在，或不是本次部署安装。"
    return
  }
  Write-UninstallLog "正在卸载本次部署安装的 uv。"
  $targets = New-Object System.Collections.Generic.List[string]
  if ($Dependency.after_path) {
    $targets.Add([string]$Dependency.after_path)
    $targets.Add((Join-Path (Split-Path -Parent ([string]$Dependency.after_path)) "uvx.exe"))
  }
  $userBin = Join-Path $env:USERPROFILE ".local\bin"
  $targets.Add((Join-Path $userBin "uv.exe"))
  $targets.Add((Join-Path $userBin "uvx.exe"))
  foreach ($target in ($targets | Select-Object -Unique)) {
    if ($target -and (Test-Path -LiteralPath $target)) {
      try {
        Remove-Item -LiteralPath $target -Force
        Write-UninstallLog "已删除 uv 文件：$target"
      } catch {
        Write-UninstallLog "uv 文件删除失败：$target；$($_.Exception.Message)"
      }
    }
  }
}

function Invoke-WingetUninstall([string]$PackageId, [string]$Label) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    Write-UninstallLog "未找到 winget，无法自动卸载 $Label。"
    return
  }
  Write-UninstallLog "正在通过 winget 卸载 $Label：$PackageId"
  try {
    $args = @(
      "uninstall",
      "--id", $PackageId,
      "-e",
      "--accept-source-agreements",
      "--silent"
    )
    $proc = Start-Process -FilePath $winget.Source -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
    Write-UninstallLog "$Label winget 卸载退出码：$($proc.ExitCode)"
  } catch {
    Write-UninstallLog "$Label winget 卸载失败：$($_.Exception.Message)"
  }
}

function Remove-NodeInstalledByDeployer($Dependency) {
  if (-not (Should-UninstallDependency $Dependency)) {
    Write-UninstallLog "保留 Node.js：部署前已存在，或不是本次部署安装。"
    return
  }
  Invoke-WingetUninstall "OpenJS.NodeJS.LTS" "Node.js LTS"
}

function Split-UninstallString([string]$CommandLine) {
  if (-not $CommandLine) { return @("", "") }
  $trimmed = $CommandLine.Trim()
  if ($trimmed.StartsWith('"')) {
    $end = $trimmed.IndexOf('"', 1)
    if ($end -gt 0) {
      return @($trimmed.Substring(1, $end - 1), $trimmed.Substring($end + 1).Trim())
    }
  }
  $parts = $trimmed.Split(@(' '), 2)
  if ($parts.Count -eq 1) { return @($parts[0], "") }
  return @($parts[0], $parts[1])
}

function Invoke-RegistryUninstall([string]$DisplayNamePattern, [string]$Label) {
  $roots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
  )
  foreach ($root in $roots) {
    $entry = Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -and ($_.DisplayName -like $DisplayNamePattern) } |
      Select-Object -First 1
    if ($entry) {
      $commandLine = $entry.QuietUninstallString
      if (-not $commandLine) { $commandLine = $entry.UninstallString }
      if (-not $commandLine) {
        Write-UninstallLog "$Label 存在卸载项，但没有卸载命令。"
        return $false
      }
      $split = Split-UninstallString $commandLine
      $file = $split[0]
      $args = $split[1]
      if ($file -and (Test-Path -LiteralPath $file)) {
        try {
          Write-UninstallLog "正在运行 $Label 卸载程序：$file $args"
          $proc = Start-Process -FilePath $file -ArgumentList $args -Wait -PassThru
          Write-UninstallLog "$Label 卸载程序退出码：$($proc.ExitCode)"
          return $true
        } catch {
          Write-UninstallLog "$Label 卸载程序运行失败：$($_.Exception.Message)"
          return $false
        }
      }
    }
  }
  return $false
}

function Remove-OllamaInstalledByDeployer($Dependency) {
  if (-not (Should-UninstallDependency $Dependency)) {
    Write-UninstallLog "保留 Ollama：部署前已存在，或不是本次部署安装。"
    return
  }
  Write-UninstallLog "正在卸载本次部署安装的 Ollama。"
  $removed = Invoke-RegistryUninstall "*Ollama*" "Ollama"
  if (-not $removed) {
    Invoke-WingetUninstall "Ollama.Ollama" "Ollama"
  }
}

function Remove-TrackedDependencies($Manifest) {
  if (-not $Manifest -or -not $Manifest.dependencies) {
    Write-UninstallLog "没有可用的依赖安装清单；将保留 uv、Node.js 和 Ollama。"
    return
  }
  Remove-UvInstalledByDeployer $Manifest.dependencies.uv
  Remove-NodeInstalledByDeployer $Manifest.dependencies.node
  Remove-OllamaInstalledByDeployer $Manifest.dependencies.ollama
}

function Remove-ProjectRoot([string]$Root) {
  Write-UninstallLog "正在删除安装目录：$Root"
  for ($attempt = 1; $attempt -le 3; $attempt += 1) {
    try {
      Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction Stop
      Write-UninstallLog "安装目录已删除。"
      return
    } catch {
      Write-UninstallLog "第 $attempt 次删除安装目录失败：$($_.Exception.Message)"
      Start-Sleep -Seconds 2
    }
  }
  throw "安装目录删除失败，请关闭相关窗口后手动删除：$Root"
}

$script:LogLines = @()
$logDir = Join-Path ([System.IO.Path]::GetTempPath()) "WebVirtualPersona-Uninstall"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$script:LogPath = Join-Path $logDir ("uninstall-" + (Get-Date).ToString("yyyyMMdd-HHmmss") + ".log")

try {
  $manifest = Load-Manifest $ManifestPath
  if (-not $ProjectRoot -and $manifest -and $manifest.project_root) {
    $ProjectRoot = [string]$manifest.project_root
  }
  $safeRoot = Assert-SafeProjectRoot $ProjectRoot $manifest

  if (-not $AssumeYes) {
    $confirm = [System.Windows.Forms.MessageBox]::Show(
      "将卸载 Web虚拟分身并删除安装目录：`n$safeRoot`n`n只会尝试卸载本次部署安装的 uv、Node.js 或 Ollama；如果部署前已经存在，将会保留。是否继续？",
      "Web虚拟分身 卸载",
      [System.Windows.Forms.MessageBoxButtons]::YesNo,
      [System.Windows.Forms.MessageBoxIcon]::Warning
    )
    if ($confirm -ne [System.Windows.Forms.DialogResult]::Yes) {
      Write-UninstallLog "用户取消卸载。"
      exit 0
    }
  }

  Write-UninstallLog "开始卸载 Web虚拟分身。"
  Write-UninstallLog "安装目录：$safeRoot"
  Stop-ProjectProcesses $safeRoot
  Remove-TrackedDependencies $manifest
  Remove-ProjectRoot $safeRoot
  Show-Info "卸载完成。`n`n日志已保存到：$script:LogPath"
} catch {
  Write-UninstallLog "卸载失败：$($_.Exception.Message)"
  Show-WarningMessage "卸载没有完全完成：$($_.Exception.Message)`n`n日志已保存到：$script:LogPath"
  exit 1
}

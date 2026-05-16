param(
    [string]$Repo = $env:WEB_VIRTUAL_PERSONA_REPO,
    [string]$Branch = $env:WEB_VIRTUAL_PERSONA_BRANCH,
    [string]$Destination = $env:WEB_VIRTUAL_PERSONA_DIR,
    [string]$GuiScriptUrl = $env:WEB_VIRTUAL_PERSONA_GUI_SCRIPT_URL,
    [switch]$Replace,
    [switch]$DryRun,
    [switch]$NoGui
)

$ErrorActionPreference = "Stop"

if (-not $Repo) { $Repo = "yushugulao/Web_Virtual_Persona" }
if (-not $Branch) { $Branch = "main" }
if (-not $Destination) { $Destination = "C:\WebVirtualPersona" }
if ($env:WEB_VIRTUAL_PERSONA_REPLACE -eq "1") { $Replace = $true }
if ($env:WEB_VIRTUAL_PERSONA_NO_GUI -eq "1") { $NoGui = $true }
if ($env:WEB_VIRTUAL_PERSONA_DRY_RUN -eq "1") { $DryRun = $true }
if (-not $GuiScriptUrl) {
    $GuiScriptUrl = "https://raw.githubusercontent.com/$Repo/$Branch/scripts/deploy/windows_local_gui_deploy.ps1"
}

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
}

function Save-RemoteUtf8Script([string]$Url, [string]$Path) {
    # Windows PowerShell 5.1 treats UTF-8 files without BOM as the local ANSI code page.
    # GitHub raw serves this script as UTF-8 without BOM, so rewrite it with BOM before -File.
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
    [System.IO.File]::WriteAllText($Path, $text, $utf8Bom)
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
    throw "PowerShell executable was not found. Ensure Windows PowerShell 5.1 is available, or repair PATH and retry."
}

function Test-ProjectDirectory([string]$Path) {
    return (Test-Path -LiteralPath (Join-Path $Path "pyproject.toml")) -and
        (Test-Path -LiteralPath (Join-Path $Path "app\frontend\package.json")) -and
        (Test-Path -LiteralPath (Join-Path $Path "scripts\deploy"))
}

function Download-Source([string]$Target) {
    $url = "https://codeload.github.com/$Repo/zip/refs/heads/$Branch"
    $temp = Join-Path ([System.IO.Path]::GetTempPath()) ("web-avatar-source-" + [System.Guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $temp "source.zip"
    Write-Step "Downloading project files from $Repo@$Branch"
    if ($DryRun) {
        Write-Host "Would download project files."
        Write-Host "Install directory: $Target"
        return
    }

    if ((Test-Path -LiteralPath $Target) -and (Test-ProjectDirectory $Target) -and -not $Replace) {
        Write-Host "Using existing project directory: $Target"
        return
    }

    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    try {
        Invoke-WebRequest -Uri $url -OutFile $zipPath
        Expand-Archive -Path $zipPath -DestinationPath $temp -Force
        $extracted = Get-ChildItem -Path $temp -Directory |
            Where-Object { $_.Name -like "*Web_Virtual_Persona*" -or $_.Name -like "*-$Branch" } |
            Select-Object -First 1
        if (-not $extracted) {
            $extracted = Get-ChildItem -Path $temp -Directory | Select-Object -First 1
        }
        if (-not $extracted) {
            throw "Downloaded archive did not contain a project directory."
        }

        if ((Test-Path -LiteralPath $Target) -and $Replace) {
            Remove-Item -LiteralPath $Target -Recurse -Force
        } elseif ((Test-Path -LiteralPath $Target) -and -not (Test-ProjectDirectory $Target)) {
            $children = @(Get-ChildItem -LiteralPath $Target -Force -ErrorAction SilentlyContinue)
            if ($children.Count -eq 0) {
                Remove-Item -LiteralPath $Target -Force
            }
        }
        if (-not (Test-Path -LiteralPath $Target)) {
            $parent = Split-Path -Parent $Target
            if ($parent -and -not (Test-Path -LiteralPath $parent)) {
                [System.IO.Directory]::CreateDirectory($parent) | Out-Null
            }
            Move-Item -LiteralPath $extracted.FullName -Destination $Target
        } elseif (-not (Test-ProjectDirectory $Target)) {
            throw "Destination already exists but is not a Web Virtual Persona project. Use -Replace or choose WEB_VIRTUAL_PERSONA_DIR."
        }
    } finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Start-LocalGui {
    $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("web-avatar-gui-" + [System.Guid]::NewGuid().ToString("N"))
    $guiScript = Join-Path $tempDir "windows_local_gui_deploy.ps1"
    $localGuiScript = $null
    if ($PSScriptRoot) {
        $localGuiScript = Join-Path $PSScriptRoot "scripts\deploy\windows_local_gui_deploy.ps1"
    }
    Write-Step "Opening Windows graphical deployment"
    if ($DryRun) {
        if ($localGuiScript -and (Test-Path -LiteralPath $localGuiScript)) {
            Write-Host "Would open the graphical deployment window from local files."
        } else {
            Write-Host "Would download the graphical deployment window."
        }
        Write-Host "Default install directory: $Destination"
        return
    }
    if ($localGuiScript -and (Test-Path -LiteralPath $localGuiScript)) {
        $guiScript = $localGuiScript
    } else {
        New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
        Save-RemoteUtf8Script -Url $GuiScriptUrl -Path $guiScript
    }
    $powershell = Get-PowerShellExecutable
    $guiArgs = @(
        "-NoProfile",
        "-STA",
        "-ExecutionPolicy", "Bypass",
        "-File", $guiScript,
        "-Repo", $Repo,
        "-Branch", $Branch,
        "-DefaultProjectRoot", $Destination
    )
    if ($Replace) { $guiArgs += "-Replace" }
    & $powershell @guiArgs
}

function Start-CommandLineWizard {
    Download-Source -Target $Destination
    if ($DryRun) { return }
    Write-Step "Starting command-line deployment"
    Set-Location -LiteralPath $Destination
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python was not found. Use the graphical deployment command, or install Python 3.11+ before using command-line deployment."
    }
    & $python.Source scripts/deploy/portable_deploy.py --mode local_lan
}

if ($NoGui) {
    Start-CommandLineWizard
} else {
    Start-LocalGui
}

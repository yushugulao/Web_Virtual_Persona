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
if (-not $GuiScriptUrl) {
    $GuiScriptUrl = "https://raw.githubusercontent.com/$Repo/$Branch/scripts/deploy/windows_local_gui_deploy.ps1"
}

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
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
    Write-Step "Downloading Web Virtual Persona source from $Repo@$Branch"
    if ($DryRun) {
        Write-Host "Would download $url"
        Write-Host "Would extract into $Target"
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
            if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
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
    Write-Step "Downloading small Windows GUI deployment package"
    if ($DryRun) {
        Write-Host "Would download $GuiScriptUrl"
        Write-Host "Would launch GUI with default install dir $Destination"
        return
    }
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    Invoke-WebRequest -Uri $GuiScriptUrl -OutFile $guiScript
    $powershell = (Get-Command powershell.exe -ErrorAction SilentlyContinue).Source
    if (-not $powershell) {
        $powershell = (Get-Command powershell -ErrorAction Stop).Source
    }
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
    Write-Step "Starting command-line deployment wizard"
    Set-Location -LiteralPath $Destination
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python was not found. Re-run without -NoGui to use the Windows GUI installer, or install Python 3.11+ first."
    }
    & $python.Source scripts/deploy/portable_deploy.py --mode local_lan
}

if ($NoGui) {
    Start-CommandLineWizard
} else {
    Start-LocalGui
}

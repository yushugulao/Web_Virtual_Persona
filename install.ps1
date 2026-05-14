param(
    [string]$Repo = $env:WEB_VIRTUAL_PERSONA_REPO,
    [string]$Branch = $env:WEB_VIRTUAL_PERSONA_BRANCH,
    [string]$Destination = $env:WEB_VIRTUAL_PERSONA_DIR,
    [switch]$Replace,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $Repo) { $Repo = "yushugulao/Web_Virtual_Persona" }
if (-not $Branch) { $Branch = "main" }
if (-not $Destination) { $Destination = Join-Path $HOME "Web_Virtual_Persona" }
if ($env:WEB_VIRTUAL_PERSONA_REPLACE -eq "1") { $Replace = $true }

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
}

function Require-Command([string]$Name, [string]$InstallHint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

function Download-Source {
    $url = "https://codeload.github.com/$Repo/zip/refs/heads/$Branch"
    $temp = Join-Path ([System.IO.Path]::GetTempPath()) ("web-avatar-" + [System.Guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $temp "source.zip"
    Write-Step "Downloading Web Virtual Persona from $Repo@$Branch"
    if ($DryRun) {
        Write-Host "Would download $url"
        Write-Host "Would extract into $Destination"
        return
    }
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    Invoke-WebRequest -Uri $url -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $temp -Force
    $extracted = Get-ChildItem -Path $temp -Directory | Where-Object { $_.Name -like "*Web_Virtual_Persona*" -or $_.Name -like "*-$Branch" } | Select-Object -First 1
    if (-not $extracted) {
        $extracted = Get-ChildItem -Path $temp -Directory | Select-Object -First 1
    }
    if ((Test-Path $Destination) -and $Replace) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    if (-not (Test-Path $Destination)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
        Move-Item -LiteralPath $extracted.FullName -Destination $Destination
    } else {
        Write-Host "Using existing project directory: $Destination"
    }
}

function Main {
    Require-Command "python" "Install Python 3.11+ from https://www.python.org/downloads/ and rerun this command."
    Download-Source
    if ($DryRun) {
        return
    }
    Set-Location $Destination
    Write-Step "Starting deployment wizard"
    $deployArgs = @()
    if ($DryRun) { $deployArgs += "--dry-run" }
    python scripts/deploy/portable_deploy.py @deployArgs
}

Main

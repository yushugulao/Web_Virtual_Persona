param(
  [string]$WorkDir = "models/document_reader/docker/paddleocr_vl",
  [int]$EndpointPort = 18080,
  [switch]$Pull,
  [switch]$Start,
  [switch]$InstallDockerDesktop,
  [switch]$OfflineImage
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$workPath = Join-Path $root $WorkDir
$composeUrl = "https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/deploy/paddleocr_vl_docker/accelerators/nvidia-gpu-sm120/compose.yaml"
$envUrl = "https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/deploy/paddleocr_vl_docker/accelerators/nvidia-gpu-sm120/.env"

function Test-CommandAvailable {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Step {
  param([string]$Message)
  Write-Host "==> $Message"
}

Write-Step "Checking host GPU"
if (Test-CommandAvailable "nvidia-smi") {
  & nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader
} else {
  Write-Warning "nvidia-smi is not available on PATH."
}

Write-Step "Checking WSL2"
if (Test-CommandAvailable "wsl") {
  try {
    & wsl --status
  } catch {
    Write-Warning "wsl --status failed: $($_.Exception.Message)"
  }
} else {
  Write-Warning "wsl.exe is not available. Install WSL2 before Docker GPU passthrough."
}

Write-Step "Preparing PaddleOCR-VL compose directory: $workPath"
New-Item -ItemType Directory -Force -Path $workPath | Out-Null
$composePath = Join-Path $workPath "compose.yaml"
$envPath = Join-Path $workPath ".env"
Invoke-WebRequest -Uri $composeUrl -OutFile $composePath
Invoke-WebRequest -Uri $envUrl -OutFile $envPath

Write-Step "Patching compose port to 127.0.0.1:$EndpointPort"
$composeText = Get-Content -Raw -Encoding UTF8 $composePath
$composeText = $composeText -replace '(?m)^\s*-\s*"?8080:8080"?\s*$', "      - `"127.0.0.1:$EndpointPort`:8080`""
$composeText = $composeText -replace '(?m)^\s*-\s*"?0\.0\.0\.0:8080:8080"?\s*$', "      - `"127.0.0.1:$EndpointPort`:8080`""
if ($composeText -notmatch "127\.0\.0\.1:$EndpointPort`:8080" -and $composeText -notmatch "127\.0\.0\.1:$EndpointPort:8080") {
  $composeText = $composeText -replace '(?m)^(\s*ports:\s*\r?\n)', "`$1      - `"127.0.0.1:$EndpointPort`:8080`"`r`n"
}
Set-Content -Encoding UTF8 -Path $composePath -Value $composeText

if ($OfflineImage) {
  Write-Step "Selecting offline image tags"
  $envText = Get-Content -Raw -Encoding UTF8 $envPath
  $envText = $envText -replace 'latest-nvidia-gpu-sm120(?!-offline)', 'latest-nvidia-gpu-sm120-offline'
  $envText = $envText -replace 'latest-nvidia-gpu(?!-offline)', 'latest-nvidia-gpu-offline'
  Set-Content -Encoding UTF8 -Path $envPath -Value $envText
}

if (-not (Test-CommandAvailable "docker")) {
  if ($InstallDockerDesktop) {
    if (-not (Test-CommandAvailable "winget")) {
      throw "Docker is missing and winget is not available. Install Docker Desktop manually."
    }
    Write-Step "Installing Docker Desktop with winget"
    & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    Write-Warning "Docker Desktop installation may require logout/reboot and a Docker Desktop start before continuing."
  } else {
    throw "Docker is missing. Re-run with -InstallDockerDesktop or install Docker Desktop manually."
  }
}

Write-Step "Docker versions"
& docker --version
& docker compose version

Write-Step "Testing Docker GPU passthrough"
try {
  & docker run --rm --gpus all --entrypoint nvidia-smi ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu-sm120
} catch {
  Write-Warning "Docker GPU passthrough smoke failed. The compose files were still prepared. Error: $($_.Exception.Message)"
}

if ($Pull) {
  Write-Step "Pulling PaddleOCR-VL Docker images"
  Push-Location $workPath
  try {
    & docker compose pull
  } finally {
    Pop-Location
  }
}

if ($Start) {
  Write-Step "Starting PaddleOCR-VL HTTP service"
  Push-Location $workPath
  try {
    & docker compose up -d
  } finally {
    Pop-Location
  }
  Write-Step "Service target: http://127.0.0.1:$EndpointPort"
}

Write-Step "Done"
Write-Host "Compose directory: $workPath"
Write-Host "Configure backend with:"
Write-Host "  DOCUMENT_READER_ENABLE_PADDLEOCR_VL=true"
Write-Host "  DOCUMENT_READER_PADDLEOCR_VL_MODE=http"
Write-Host "  DOCUMENT_READER_PADDLEOCR_VL_ENDPOINT=http://127.0.0.1:$EndpointPort"
Write-Host "  DOCUMENT_READER_PADDLEOCR_VL_DEVICE=gpu"

param(
    [string]$Endpoint = "http://127.0.0.1:18080",
    [int]$DockerWaitSeconds = 600,
    [switch]$SkipBenchmark
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format HH:mm:ss)] $Message"
}

$dockerBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
if (Test-Path $dockerBin) {
    $env:Path = "$dockerBin;$env:Path"
}

Write-Step "Checking Docker CLI."
docker --version
docker compose version

$dockerDesktop = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"
if (Test-Path $dockerDesktop) {
    Write-Step "Starting Docker Desktop if needed."
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
}

Write-Step "Waiting for Docker Engine."
$deadline = (Get-Date).AddSeconds($DockerWaitSeconds)
do {
    $info = docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Step "Docker Engine is ready."
        break
    }
    Start-Sleep -Seconds 10
} while ((Get-Date) -lt $deadline)

if ($LASTEXITCODE -ne 0) {
    Write-Host $info
    throw "Docker Engine did not become ready within $DockerWaitSeconds seconds."
}

Write-Step "Testing GPU passthrough in Docker."
docker run --rm --gpus all --entrypoint nvidia-smi `
    ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu-sm120

Write-Step "Starting PaddleOCR-VL Docker HTTP service."
.\scripts\document_reader\setup_paddleocr_vl_docker.ps1 -Pull -Start

$env:DOCUMENT_READER_ENABLE_PADDLEOCR_VL = "true"
$env:DOCUMENT_READER_PADDLEOCR_VL_MODE = "http"
$env:DOCUMENT_READER_PADDLEOCR_VL_ENDPOINT = $Endpoint
$env:DOCUMENT_READER_PADDLEOCR_VL_DEVICE = "gpu"

Write-Step "Checking document-reader backends."
uv run python scripts\document_reader\check_backends.py --json

if (-not $SkipBenchmark) {
    Write-Step "Preparing benchmark fixtures."
    uv run python scripts\document_reader\prepare_benchmark_fixtures.py

    Write-Step "Running full OCR-heavy PaddleOCR-VL benchmark."
    uv run python scripts\document_reader\run_fixture_benchmark.py --suite paddleocr_vl --paddle-mode http
}

Write-Step "Done."

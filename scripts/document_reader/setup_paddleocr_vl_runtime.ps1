param(
    [ValidateSet("auto", "cpu", "gpu")]
    [string]$Device = "auto",
    [string]$RuntimeDir = "models/document_reader/runtimes/paddleocr_vl",
    [string]$Python = "python",
    [string]$PaddlePackage = "paddlepaddle",
    [string]$PaddleIndexUrl = "",
    [switch]$SkipInstall,
    [switch]$RunSmoke
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runtimePath = Join-Path $root $RuntimeDir
$venvPath = Join-Path $runtimePath ".venv"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
$cacheDir = Join-Path $root "models\document_reader"

New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

$env:PADDLE_HOME = Join-Path $cacheDir "paddle"
$env:HF_HOME = Join-Path $cacheDir "huggingface"
$env:HF_HUB_CACHE = Join-Path $cacheDir "huggingface\hub"
$env:HUGGINGFACE_HUB_CACHE = $env:HF_HUB_CACHE
$env:TRANSFORMERS_CACHE = $env:HF_HUB_CACHE
$env:MODELSCOPE_CACHE = Join-Path $cacheDir "modelscope"
$env:XDG_CACHE_HOME = Join-Path $cacheDir "xdg"

if ($Python -eq "python" -or -not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    $uvPython = (& uv python find 2>$null)
    if ($LASTEXITCODE -eq 0 -and $uvPython) {
        $Python = $uvPython.Trim()
        Write-Host "Using uv Python: $Python"
    }
}

if (-not (Test-Path $pythonExe)) {
    Write-Host "Creating isolated PaddleOCR-VL runtime at $venvPath"
    & $Python -m venv $venvPath
}

if (-not $SkipInstall) {
    & $pythonExe -m pip install --upgrade pip setuptools wheel
    $paddleArgs = @("install", $PaddlePackage)
    if ($PaddleIndexUrl.Trim()) {
        $paddleArgs += @("-i", $PaddleIndexUrl)
    }
    Write-Host "Installing PaddlePaddle package: $PaddlePackage"
    & $pythonExe -m pip @paddleArgs
    Write-Host "Installing PaddleOCR document parser extras"
    & $pythonExe -m pip install "paddleocr[doc-parser]"
}

$worker = Join-Path $root "scripts\document_reader\paddleocr_vl_worker.py"
Write-Host "Checking PaddleOCR-VL worker"
& $pythonExe $worker --check --cache-dir $cacheDir

if ($RunSmoke) {
    $fixtureDir = Join-Path $root "data\cache\document_reader_benchmark\setup_smoke"
    New-Item -ItemType Directory -Force -Path $fixtureDir | Out-Null
    $fixture = Join-Path $fixtureDir "smoke.txt"
    Set-Content -Path $fixture -Value "PaddleOCR-VL smoke fixture" -Encoding UTF8
    & $pythonExe $worker $fixture --output-dir $fixtureDir --filename "smoke.txt" --device $Device --cache-dir $cacheDir
}

Write-Host ""
Write-Host "PaddleOCR-VL runtime ready."
Write-Host "Set these local .env values after smoke succeeds:"
Write-Host "DOCUMENT_READER_ENABLE_PADDLEOCR_VL=true"
Write-Host "DOCUMENT_READER_PADDLEOCR_VL_MODE=worker"
Write-Host "DOCUMENT_READER_PADDLEOCR_VL_PYTHON=$pythonExe"
Write-Host "DOCUMENT_READER_PADDLEOCR_VL_DEVICE=$Device"

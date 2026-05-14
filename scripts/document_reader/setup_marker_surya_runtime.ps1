param(
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$Device = "auto",
    [string]$RuntimeDir = "models/document_reader/runtimes/marker_surya",
    [string]$Python = "python",
    [string]$MarkerPackage = "marker-pdf[full]",
    [switch]$SkipInstall,
    [switch]$RunSmoke
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runtimePath = Join-Path $root $RuntimeDir
$venvPath = Join-Path $runtimePath ".venv"
$windowsPython = Join-Path $venvPath "Scripts\python.exe"
$posixPython = Join-Path $venvPath "bin\python"
$cacheDir = Join-Path $root "models\document_reader"

New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

$env:HF_HOME = Join-Path $cacheDir "huggingface"
$env:HF_HUB_CACHE = Join-Path $cacheDir "huggingface\hub"
$env:HUGGINGFACE_HUB_CACHE = $env:HF_HUB_CACHE
$env:TRANSFORMERS_CACHE = $env:HF_HUB_CACHE
$env:TORCH_HOME = Join-Path $cacheDir "torch"
$env:XDG_CACHE_HOME = Join-Path $cacheDir "xdg"
if ($Device -ne "auto") {
    $env:TORCH_DEVICE = $Device
}

if ($Python -eq "python" -or -not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    $uvPython = (& uv python find 2>$null)
    if ($LASTEXITCODE -eq 0 -and $uvPython) {
        $Python = $uvPython.Trim()
        Write-Host "Using uv Python: $Python"
    }
}

if (-not (Test-Path $windowsPython) -and -not (Test-Path $posixPython)) {
    Write-Host "Creating isolated Marker/Surya runtime at $venvPath"
    & $Python -m venv $venvPath
}

$pythonExe = if (Test-Path $windowsPython) { $windowsPython } else { $posixPython }

if (-not $SkipInstall) {
    & $pythonExe -m pip install --upgrade pip setuptools wheel
    Write-Host "Installing Marker/Surya package: $MarkerPackage"
    & $pythonExe -m pip install $MarkerPackage
}

$worker = Join-Path $root "scripts\document_reader\marker_surya_worker.py"
Write-Host "Checking Marker/Surya worker"
& $pythonExe $worker --check --cache-dir $cacheDir --device $Device

if ($RunSmoke) {
    $fixtureDir = Join-Path $root "data\cache\document_reader_benchmark\marker_surya_setup_smoke"
    New-Item -ItemType Directory -Force -Path $fixtureDir | Out-Null
    $fixture = Join-Path $fixtureDir "smoke.png"
    & $pythonExe -c "from PIL import Image, ImageDraw; img=Image.new('RGB',(900,420),'white'); d=ImageDraw.Draw(img); d.text((60,80),'Marker Surya OCR smoke', fill=(20,20,20)); d.text((60,150),'中文 OCR 读取测试', fill=(20,20,20)); img.save(r'$fixture')"
    & $pythonExe $worker $fixture --output-dir $fixtureDir --filename "smoke.png" --device $Device --cache-dir $cacheDir --force-ocr
}

Write-Host ""
Write-Host "Marker/Surya runtime ready."
Write-Host "Set these local .env values after smoke succeeds:"
Write-Host "DOCUMENT_READER_ENABLE_MARKER_SURYA=true"
Write-Host "DOCUMENT_READER_MARKER_SURYA_PYTHON=$pythonExe"
Write-Host "DOCUMENT_READER_MARKER_SURYA_DEVICE=$Device"

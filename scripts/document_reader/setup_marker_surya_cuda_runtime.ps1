param(
    [string]$RuntimeDir = "models/document_reader/runtimes/marker_surya_cuda",
    [string]$Python = "python",
    [string]$MarkerPackage = "marker-pdf[full]",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128",
    [string]$NightlyTorchIndexUrl = "https://download.pytorch.org/whl/nightly/cu128",
    [switch]$UseNightly,
    [switch]$NoNightlyFallback,
    [switch]$SkipMarkerInstall,
    [switch]$SkipTorchInstall,
    [switch]$RunSmoke,
    [switch]$UpdateLocalEnv
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runtimePath = Join-Path $root $RuntimeDir
$venvPath = Join-Path $runtimePath ".venv"
$windowsPython = Join-Path $venvPath "Scripts\python.exe"
$posixPython = Join-Path $venvPath "bin\python"
$cacheDir = Join-Path $root "models\document_reader"
$pipCacheDir = Join-Path $cacheDir "pip"

function Set-ReaderCacheEnv {
    param([string]$CacheDir)
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "huggingface\hub") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "torch") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "xdg") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "pip") | Out-Null
    $env:HF_HOME = Join-Path $CacheDir "huggingface"
    $env:HF_HUB_CACHE = Join-Path $CacheDir "huggingface\hub"
    $env:HUGGINGFACE_HUB_CACHE = $env:HF_HUB_CACHE
    $env:TRANSFORMERS_CACHE = $env:HF_HUB_CACHE
    $env:TORCH_HOME = Join-Path $CacheDir "torch"
    $env:XDG_CACHE_HOME = Join-Path $CacheDir "xdg"
    $env:PIP_CACHE_DIR = Join-Path $CacheDir "pip"
    $env:TORCH_DEVICE = "cuda"
}

function Get-ProjectPython {
    param([string]$RequestedPython)
    if ($RequestedPython -eq "python" -or -not (Get-Command $RequestedPython -ErrorAction SilentlyContinue)) {
        $uvPython = (& uv python find 2>$null)
        if ($LASTEXITCODE -eq 0 -and $uvPython) {
            return $uvPython.Trim()
        }
    }
    return $RequestedPython
}

function Test-CudaTorch {
    param([string]$PythonExe)
    $check = @'
import json
payload = {"ok": False}
try:
    import torch
    payload.update({
        "torch": getattr(torch, "__version__", ""),
        "torch_cuda_version": getattr(torch.version, "cuda", None),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_count": int(torch.cuda.device_count()) if torch.cuda.is_available() else 0,
    })
    if torch.cuda.is_available():
        payload["cuda_device_name"] = torch.cuda.get_device_name(0)
        payload["cuda_device_capability"] = list(torch.cuda.get_device_capability(0))
        payload["ok"] = True
except Exception as exc:
    payload["error"] = str(exc)
print(json.dumps(payload, ensure_ascii=False))
raise SystemExit(0 if payload.get("ok") else 10)
'@
    $output = & $PythonExe -c $check
    $exitCode = $LASTEXITCODE
    if ($output) {
        Write-Host $output
    }
    return $exitCode -eq 0
}

function Install-CudaTorch {
    param(
        [string]$PythonExe,
        [string]$IndexUrl,
        [switch]$Preview
    )
    $previewArgs = @()
    if ($Preview) {
        $previewArgs = @("--pre")
    }
    Write-Host "Installing official PyTorch CUDA wheels from $IndexUrl"
    & $PythonExe -m pip install --upgrade --force-reinstall @previewArgs torch torchvision torchaudio --index-url $IndexUrl
    if ($LASTEXITCODE -ne 0) {
        throw "PyTorch CUDA install failed from $IndexUrl"
    }
    Write-Host "Restoring Marker/Surya-compatible Pillow after CUDA torch install"
    & $PythonExe -m pip install "Pillow<11,>=10.2.0"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Marker/Surya-compatible Pillow version."
    }
}

function Update-EnvFile {
    param(
        [string]$EnvPath,
        [hashtable]$Values
    )
    $lines = @()
    if (Test-Path $EnvPath) {
        $lines = Get-Content $EnvPath -Encoding UTF8
    }
    foreach ($key in $Values.Keys) {
        $value = [string]$Values[$key]
        $escaped = $value -replace "\\", "\\"
        $pattern = "^$([Regex]::Escape($key))="
        $found = $false
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match $pattern) {
                $lines[$i] = "$key=$escaped"
                $found = $true
            }
        }
        if (-not $found) {
            $lines += "$key=$escaped"
        }
    }
    Set-Content -Path $EnvPath -Value $lines -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
New-Item -ItemType Directory -Force -Path $pipCacheDir | Out-Null
Set-ReaderCacheEnv -CacheDir $cacheDir

$Python = Get-ProjectPython -RequestedPython $Python
Write-Host "Using Python: $Python"

if (-not (Test-Path $windowsPython) -and -not (Test-Path $posixPython)) {
    Write-Host "Creating isolated Marker/Surya CUDA runtime at $venvPath"
    & $Python -m venv $venvPath
}

$pythonExe = if (Test-Path $windowsPython) { $windowsPython } else { $posixPython }

& $pythonExe -m pip install --upgrade pip setuptools wheel

if (-not $SkipMarkerInstall) {
    Write-Host "Installing Marker/Surya package: $MarkerPackage"
    & $pythonExe -m pip install $MarkerPackage
}

if (-not $SkipTorchInstall) {
    if ($UseNightly) {
        Install-CudaTorch -PythonExe $pythonExe -IndexUrl $NightlyTorchIndexUrl -Preview
    } else {
        Install-CudaTorch -PythonExe $pythonExe -IndexUrl $TorchIndexUrl
    }
}

$cudaOk = Test-CudaTorch -PythonExe $pythonExe
if (-not $cudaOk -and -not $UseNightly -and -not $NoNightlyFallback) {
    Write-Host "Stable CUDA wheel did not expose CUDA. Trying official nightly CUDA wheel..."
    Install-CudaTorch -PythonExe $pythonExe -IndexUrl $NightlyTorchIndexUrl -Preview
    $cudaOk = Test-CudaTorch -PythonExe $pythonExe
}
if (-not $cudaOk) {
    throw "CUDA torch check failed. Do not use this runtime for marker_surya cuda until torch.cuda.is_available() is true."
}

$worker = Join-Path $root "scripts\document_reader\marker_surya_worker.py"
Write-Host "Checking Marker/Surya CUDA worker"
& $pythonExe $worker --check --cache-dir $cacheDir --device cuda
if ($LASTEXITCODE -ne 0) {
    throw "Marker/Surya CUDA worker check failed."
}

if ($RunSmoke) {
    $fixtureDir = Join-Path $root "data\cache\document_reader_benchmark\marker_surya_cuda_setup_smoke"
    New-Item -ItemType Directory -Force -Path $fixtureDir | Out-Null
    $fixture = Join-Path $fixtureDir "smoke.png"
    & $pythonExe -c "from PIL import Image, ImageDraw; img=Image.new('RGB',(900,420),'white'); d=ImageDraw.Draw(img); d.text((60,80),'Marker Surya CUDA OCR smoke', fill=(20,20,20)); d.text((60,150),'中文 OCR GPU 读取测试', fill=(20,20,20)); img.save(r'$fixture')"
    & $pythonExe $worker $fixture --output-dir $fixtureDir --filename "smoke.png" --device cuda --cache-dir $cacheDir --force-ocr
}

if ($UpdateLocalEnv) {
    $envPath = Join-Path $root ".env"
    Update-EnvFile -EnvPath $envPath -Values @{
        "DOCUMENT_READER_ENABLE_MARKER_SURYA" = "true"
        "DOCUMENT_READER_MARKER_SURYA_PYTHON" = $pythonExe
        "DOCUMENT_READER_MARKER_SURYA_DEVICE" = "cuda"
        "DOCUMENT_READER_MARKER_SURYA_TIMEOUT_SECONDS" = "900"
        "DOCUMENT_READER_ENABLE_PADDLEOCR_VL" = "false"
    }
    Write-Host "Updated local .env with Marker/Surya CUDA runtime values."
}

Write-Host ""
Write-Host "Marker/Surya CUDA runtime ready."
Write-Host "Set these local .env values:"
Write-Host "DOCUMENT_READER_ENABLE_MARKER_SURYA=true"
Write-Host "DOCUMENT_READER_MARKER_SURYA_PYTHON=$pythonExe"
Write-Host "DOCUMENT_READER_MARKER_SURYA_DEVICE=cuda"
Write-Host "DOCUMENT_READER_ENABLE_PADDLEOCR_VL=false"

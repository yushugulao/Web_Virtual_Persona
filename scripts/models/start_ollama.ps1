$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ModelRoot = Join-Path $ProjectRoot "models"
$OllamaModels = Join-Path $ModelRoot "ollama"
$LogDir = Join-Path $ModelRoot "logs"
$OutLog = Join-Path $LogDir "ollama.out.log"
$ErrLog = Join-Path $LogDir "ollama.err.log"

& (Join-Path $PSScriptRoot "set_model_cache_env.ps1") -ProjectRoot $ProjectRoot | Out-Null

New-Item -ItemType Directory -Force $OllamaModels, $LogDir | Out-Null

function Find-Ollama {
  $cmd = Get-Command ollama -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  $candidates = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "$env:ProgramFiles\Ollama\ollama.exe",
    "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama.exe"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { return $candidate }
  }
  throw "Ollama executable not found. Install Ollama first, then run this script again."
}

$existing = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Ollama already appears to be listening on port 11434."
  Write-Host "If it was not started with OLLAMA_MODELS=$OllamaModels, stop it and rerun this script."
  exit 0
}

$ollama = Find-Ollama
Start-Process -FilePath $ollama `
  -ArgumentList @("serve") `
  -WorkingDirectory $ProjectRoot `
  -RedirectStandardOutput $OutLog `
  -RedirectStandardError $ErrLog `
  -WindowStyle Hidden `
  -PassThru | Out-Null

Start-Sleep -Seconds 3
$listener = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
  throw "Ollama did not start. Check $ErrLog"
}

Write-Host "Ollama started on http://127.0.0.1:11434"
Write-Host "OLLAMA_MODELS=$OllamaModels"

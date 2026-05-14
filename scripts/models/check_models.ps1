$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ModelRoot = Join-Path $ProjectRoot "models"
& (Join-Path $PSScriptRoot "set_model_cache_env.ps1") -ProjectRoot $ProjectRoot | Out-Null
$OllamaModels = $env:OLLAMA_MODELS

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
  return $null
}

$ollama = Find-Ollama
$listener = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue

[PSCustomObject]@{
  ProjectRoot = $ProjectRoot.Path
  ModelRoot = $ModelRoot
  OllamaModels = $OllamaModels
  HuggingFaceHub = $env:HF_HUB_CACHE
  HuggingFaceDatasets = $env:HF_DATASETS_CACHE
  HuggingFaceXet = $env:HF_XET_CACHE
  TorchHome = $env:TORCH_HOME
  ModelScopeCache = $env:MODELSCOPE_CACHE
  OllamaExecutable = $ollama
  OllamaInstalled = [bool]$ollama
  OllamaListening = [bool]$listener
  OllamaPort = 11434
}

if ($ollama) {
  & $ollama --version
}

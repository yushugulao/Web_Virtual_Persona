param(
  [string]$Model = "qwen3:8b"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
& (Join-Path $PSScriptRoot "set_model_cache_env.ps1") -ProjectRoot $ProjectRoot | Out-Null
$OllamaModels = $env:OLLAMA_MODELS

& (Join-Path $PSScriptRoot "start_ollama.ps1")

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
  $candidate = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
  if (Test-Path $candidate) {
    $ollama = [PSCustomObject]@{ Source = $candidate }
  } else {
    throw "Ollama executable not found."
  }
}

Write-Host "Pulling $Model into $OllamaModels"
& $ollama.Source pull $Model
& $ollama.Source list

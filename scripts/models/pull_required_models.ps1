param(
  [string[]]$Models = @("qwen3.5:9b", "qwen3:8b", "qwen3-embedding:0.6b"),
  [switch]$InstallMissing
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $ProjectRoot

& (Join-Path $PSScriptRoot "set_model_cache_env.ps1") -ProjectRoot $ProjectRoot | Out-Null
& (Join-Path $PSScriptRoot "start_ollama.ps1")

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
  if ($env:PERSONA_RAG_OLLAMA_EXECUTABLE -and (Test-Path -LiteralPath $env:PERSONA_RAG_OLLAMA_EXECUTABLE)) {
    $ollama = [PSCustomObject]@{ Source = $env:PERSONA_RAG_OLLAMA_EXECUTABLE }
  }
}
if (-not $ollama) {
  $candidate = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
  if (Test-Path $candidate) {
    $ollama = [PSCustomObject]@{ Source = $candidate }
  } else {
    if ($InstallMissing) {
      Write-Host "Ollama executable not found. Running portable dependency installer."
      uv run python scripts/deploy/portable_deploy.py --install-missing --non-interactive --mode local_lan --profile standard_gpu
      $ollama = Get-Command ollama -ErrorAction SilentlyContinue
      if (-not $ollama -and (Test-Path $candidate)) {
        $ollama = [PSCustomObject]@{ Source = $candidate }
      }
    }
    if (-not $ollama) {
      throw "Ollama executable not found. Run: .\scripts\deploy\portable_deploy.ps1 -InstallMissing, or set PERSONA_RAG_OLLAMA_EXECUTABLE to an existing ollama.exe."
    }
  }
}

foreach ($model in $Models) {
  Write-Host "Pulling $model"
  & $ollama.Source pull $model
}

& $ollama.Source list

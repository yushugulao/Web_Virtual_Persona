param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

& (Join-Path $projectRoot "scripts\models\set_model_cache_env.ps1") -ProjectRoot $projectRoot | Out-Null

uv run uvicorn app.backend.main:app --host $HostAddress --port $Port

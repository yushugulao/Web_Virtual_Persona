param(
  [switch]$WithDocumentReader
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $ProjectRoot

function Require-Command($Name, $Hint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name not found. $Hint Run .\scripts\deploy\portable_deploy.ps1 -InstallMissing to install missing prerequisites from official sources."
  }
}

Require-Command "uv" "Install uv from https://docs.astral.sh/uv/"
Require-Command "node" "Install Node.js 20+."
Require-Command "npm" "Install Node.js 20+."

if (-not (Test-Path -LiteralPath ".env")) {
  Copy-Item -LiteralPath ".env.windows.example" -Destination ".env"
  Write-Host "Created .env from .env.windows.example. Edit it before public use."
}

New-Item -ItemType Directory -Force `
  "data\indexes", "data\sqlite", "data\feedback", "data\logs", "data\runtime_logs", `
  "data\screenshots", "data\cache", "data\eval_reports", "models\ollama", `
  "models\huggingface", "models\document_reader", "logs" | Out-Null

if ($WithDocumentReader) {
  uv sync --extra dev --extra document-reader
} else {
  uv sync --extra dev
}

Push-Location app\frontend
try {
  npm install
} finally {
  Pop-Location
}

Write-Host "Bootstrap complete. Next: scripts\models\pull_required_models.ps1"

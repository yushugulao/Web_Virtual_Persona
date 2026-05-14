param(
  [string]$Output = "dist/public-export"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $ProjectRoot

uv run python scripts/release/create_public_export.py --output $Output
uv run python scripts/security/prepare_public_export_check.py $Output


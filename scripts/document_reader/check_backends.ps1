param(
  [switch]$Json
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$argsList = @("run", "python", "scripts/document_reader/check_backends.py")
if ($Json) {
  $argsList += "--json"
}
uv @argsList

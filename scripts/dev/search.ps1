param(
  [Parameter(Mandatory = $true, Position = 0)]
  [string]$Pattern,

  [Parameter(Position = 1)]
  [string]$Path = ".",

  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$ExtraArgs = @()
)

Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "enter_utf8_shell.ps1") -Quiet

$rg = Get-Command rg -ErrorAction SilentlyContinue
if ($rg) {
  & rg --line-number --color never --hidden `
    --glob "!node_modules" `
    --glob "!app/frontend/dist" `
    --glob "!data/screenshots" `
    --glob "!data/runtime_logs" `
    --glob "!models" `
    @ExtraArgs -- $Pattern $Path
  exit $LASTEXITCODE
}

Write-Warning "ripgrep is not available; falling back to PowerShell Select-String."
$excluded = @("node_modules", "dist", ".git", "__pycache__", "screenshots", "runtime_logs", "models")
Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
  Where-Object {
    $full = $_.FullName
    -not ($excluded | Where-Object { $full -like "*\$_\*" })
  } |
  Select-String -Pattern $Pattern -Encoding UTF8

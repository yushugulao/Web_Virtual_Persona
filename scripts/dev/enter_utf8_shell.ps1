param(
  [switch]$Quiet
)

Set-StrictMode -Version Latest

function Add-PathHead {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ((Test-Path -LiteralPath $Path) -and ($env:PATH -notlike "*$Path*")) {
    $env:PATH = "$Path;$env:PATH"
  }
}

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $utf8NoBom

try {
  [Console]::InputEncoding = $utf8NoBom
  [Console]::OutputEncoding = $utf8NoBom
} catch {
  Write-Warning "Unable to set console encoding: $($_.Exception.Message)"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:LC_ALL = "C.UTF-8"
$env:LANG = "C.UTF-8"
$env:NODE_OPTIONS = (($env:NODE_OPTIONS, "--enable-source-maps") | Where-Object { $_ } | Select-Object -Unique) -join " "

$scoopRoot = $env:SCOOP
if (-not $scoopRoot) {
  $scoopRoot = "E:\Scoop"
}
Add-PathHead (Join-Path $scoopRoot "shims")
Add-PathHead (Join-Path $scoopRoot "apps\scoop\current\bin")

if (-not $Quiet) {
  Write-Host "UTF-8 shell baseline is active."
  Write-Host "PowerShell: $($PSVersionTable.PSVersion) / $($PSVersionTable.PSEdition)"
  Write-Host "OutputEncoding: $($OutputEncoding.WebName)"
  Write-Host "ConsoleOutput: $([Console]::OutputEncoding.WebName)"
}

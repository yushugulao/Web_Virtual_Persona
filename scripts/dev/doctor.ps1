Set-StrictMode -Version Latest

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
. (Join-Path $PSScriptRoot "enter_utf8_shell.ps1")

$script:FailureCount = 0
$script:WarningCount = 0

function Pass {
  param([string]$Message)
  Write-Host "[OK]   $Message"
}

function Warn {
  param([string]$Message)
  $script:WarningCount += 1
  Write-Warning $Message
}

function Fail {
  param([string]$Message)
  $script:FailureCount += 1
  Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Test-Command {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string[]]$VersionArgs = @("--version")
  )
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $command) {
    Fail "$Name is missing from PATH."
    return
  }
  $version = ""
  try {
    $version = (& $Name @VersionArgs 2>$null | Select-Object -First 1)
  } catch {
    $version = "version check failed: $($_.Exception.Message)"
  }
  Pass "$Name -> $($command.Source) $version"
}

Write-Host "Project root: $ProjectRoot"

if ($PSVersionTable.PSEdition -ne "Core") {
  Warn "Current shell is Windows PowerShell $($PSVersionTable.PSVersion). Prefer pwsh 7 from E:\Scoop for daily work."
} else {
  Pass "Running under PowerShell Core $($PSVersionTable.PSVersion)."
}

if ($OutputEncoding.WebName -eq "utf-8" -and [Console]::OutputEncoding.WebName -eq "utf-8") {
  Pass "PowerShell output encodings are UTF-8."
} else {
  Fail "PowerShell output encoding is not UTF-8. Output=$($OutputEncoding.WebName), Console=$([Console]::OutputEncoding.WebName)"
}

foreach ($tool in @("pwsh", "rg", "fd", "jq", "yq", "bat", "delta", "7z", "git", "node", "npm", "uv")) {
  Test-Command $tool
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("persona-rag-utf8-" + [System.Guid]::NewGuid() + ".txt")
$sample = "UTF8 roundtrip: Web虚拟分身 / 蹦蹦炸弹 / 张三"
try {
  [System.IO.File]::WriteAllText($tmp, $sample, [System.Text.UTF8Encoding]::new($false))
  $readBack = [System.IO.File]::ReadAllText($tmp, [System.Text.UTF8Encoding]::new($false))
  if ($readBack -eq $sample) {
    Pass "PowerShell UTF-8 file roundtrip works."
  } else {
    Fail "PowerShell UTF-8 file roundtrip changed content."
  }
  $rgOutput = & rg "虚拟分身" $tmp 2>$null
  if ($LASTEXITCODE -eq 0 -and $rgOutput -match "虚拟分身") {
    Pass "ripgrep can read UTF-8 content."
  } else {
    Fail "ripgrep did not match UTF-8 sample text."
  }
} finally {
  if (Test-Path -LiteralPath $tmp) {
    Remove-Item -LiteralPath $tmp -Force
  }
}

try {
  $pythonOutput = uv run python -c "from pathlib import Path; p=Path('PROJECT_STATE.md'); print(p.read_text(encoding='utf-8')[:20])"
  if ($LASTEXITCODE -eq 0 -and $pythonOutput) {
    Pass "Python UTF-8 read via uv works."
  } else {
    Fail "Python UTF-8 read via uv failed."
  }
} catch {
  Fail "Python UTF-8 read via uv threw: $($_.Exception.Message)"
}

try {
  $nodeOutput = node -e "const fs=require('fs'); process.stdout.write(fs.readFileSync('PROJECT_STATE.md','utf8').slice(0,20));"
  if ($LASTEXITCODE -eq 0 -and $nodeOutput) {
    Pass "Node UTF-8 read works."
  } else {
    Fail "Node UTF-8 read failed."
  }
} catch {
  Fail "Node UTF-8 read threw: $($_.Exception.Message)"
}

$quotepath = git config --global --get core.quotepath
$logEncoding = git config --global --get i18n.logOutputEncoding
$commitEncoding = git config --global --get i18n.commitEncoding
if ($quotepath -eq "false" -and $logEncoding -eq "utf-8" -and $commitEncoding -eq "utf-8") {
  Pass "Git UTF-8 settings are configured."
} else {
  Fail "Git UTF-8 settings are incomplete: core.quotepath=$quotepath log=$logEncoding commit=$commitEncoding"
}

Write-Host ""
Write-Host "Doctor summary: $script:FailureCount failure(s), $script:WarningCount warning(s)."
if ($script:FailureCount -gt 0) {
  exit 1
}

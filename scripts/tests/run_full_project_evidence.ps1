param(
  [string]$OutputRoot = ".artifacts",
  [string]$Timestamp = "",
  [switch]$SkipFrontend,
  [switch]$SkipPublicExport
)

$ErrorActionPreference = "Stop"

if (-not $Timestamp) {
  $Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ArtifactDir = Join-Path (Resolve-Path $ProjectRoot).Path (Join-Path $OutputRoot "full_project_evidence_2026-05-19_$Timestamp")
$LogDir = Join-Path $ArtifactDir "logs"
$ApiDir = Join-Path $ArtifactDir "api"
$ScreenshotDir = Join-Path $ArtifactDir "screenshots"
$PublicExportDir = Join-Path $ArtifactDir "public-export"
$DeployTestDir = "C:\WebVirtualPersona_Test_$Timestamp"
$UninstallFixtureDir = Join-Path $ArtifactDir "uninstall-fixture"

New-Item -ItemType Directory -Force -Path $LogDir, $ApiDir, $ScreenshotDir | Out-Null

$script:Results = New-Object System.Collections.Generic.List[object]
$script:SecretValues = @()

function Update-SecretValues {
  $names = @(
    "PERSONA_RAG_DEEPSEEK_API_KEY",
    "PERSONA_RAG_SMTP_USERNAME",
    "PERSONA_RAG_SMTP_PASSWORD",
    "PERSONA_RAG_SMTP_FROM",
    "PERSONA_RAG_LIVE_EMAIL_RECIPIENT"
  )
  $values = New-Object System.Collections.Generic.List[string]
  foreach ($name in $names) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not [string]::IsNullOrWhiteSpace($value) -and $value.Length -ge 4) {
      $values.Add($value) | Out-Null
    }
  }
  $script:SecretValues = @($values | Sort-Object Length -Descending -Unique)
}

function Redact-Text([string]$Text) {
  if ($null -eq $Text) { return "" }
  $value = $Text
  foreach ($secret in $script:SecretValues) {
    $value = $value.Replace($secret, "<REDACTED>")
  }
  $value = $value -replace '(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+/=-]+', '$1<REDACTED>'
  $value = $value -replace '(?i)(token["'']?\s*[:=]\s*["'']?)[A-Za-z0-9._~+/=-]{12,}', '$1<REDACTED>'
  $value = $value -replace '(?i)(api[_-]?key["'']?\s*[:=]\s*["'']?)[A-Za-z0-9._~+/=-]{8,}', '$1<REDACTED>'
  $value = $value -replace '(?i)(password["'']?\s*[:=]\s*["'']?)[^,"''\s]+', '$1<REDACTED>'
  return $value
}

function Write-JsonFile($Path, $Value) {
  $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Add-Result([string]$Name, [string]$Status, [int]$ExitCode, [string]$Evidence, [string]$Notes = "") {
  $script:Results.Add([PSCustomObject]@{
    name = $Name
    status = $Status
    exit_code = $ExitCode
    evidence = $Evidence
    notes = $Notes
    completed_at = (Get-Date).ToString("o")
  }) | Out-Null
}

function Invoke-EvidenceCommand {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
    [string]$WorkingDirectory = $ProjectRoot,
    [bool]$Required = $true,
    [string]$Notes = ""
  )
  $safeName = $Name -replace '[^a-zA-Z0-9_.-]+', '_'
  $logPath = Join-Path $LogDir "$safeName.log"
  Push-Location $WorkingDirectory
  try {
    "### $Name" | Set-Content -LiteralPath $logPath -Encoding utf8
    "started_at=$((Get-Date).ToString('o'))" | Add-Content -LiteralPath $logPath -Encoding utf8
    $global:LASTEXITCODE = 0
    try {
      & $ScriptBlock 2>&1 | ForEach-Object {
        $line = Redact-Text ([string]$_)
        $line | Add-Content -LiteralPath $logPath -Encoding utf8
        Write-Host $line
      }
      $exitCode = if ($null -ne $global:LASTEXITCODE) { [int]$global:LASTEXITCODE } else { 0 }
    } catch {
      $exitCode = 1
      Redact-Text $_.Exception.Message | Add-Content -LiteralPath $logPath -Encoding utf8
      Write-Host $_.Exception.Message
    }
    "finished_at=$((Get-Date).ToString('o'))" | Add-Content -LiteralPath $logPath -Encoding utf8
    "exit_code=$exitCode" | Add-Content -LiteralPath $logPath -Encoding utf8
    if ($exitCode -eq 0) {
      Add-Result $Name "PASS" $exitCode $logPath $Notes
    } elseif ($Required) {
      Add-Result $Name "FAIL" $exitCode $logPath $Notes
    } else {
      Add-Result $Name "SKIPPED" $exitCode $logPath $Notes
    }
    if ($Required -and $exitCode -ne 0) {
      throw "$Name failed with exit code $exitCode"
    }
  } finally {
    Pop-Location
  }
}

function Test-CommandPresence([string]$Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  return [PSCustomObject]@{
    command = $Name
    found = [bool]$cmd
    source = if ($cmd) { $cmd.Source } else { "" }
  }
}

function New-TestMatrix {
  $matrix = @"
# Full Project Test Matrix

Artifact directory: $ArtifactDir

| Area | Evidence | Expected result |
| --- | --- | --- |
| Auth/admin/theme | pytest full project suite | register/login/session/theme/admin workflows pass |
| Health/status/models | pytest and live probes | status endpoint works; live model availability recorded |
| Corpus/ingest/retrieval/evidence/traces | pytest full project suite | corpus ingests, retrieve returns citations, traces recorded |
| Chat/session/stream/model release | pytest full project suite | sessions, messages, stream, archive/restore/delete pass |
| Memory/feedback/browser matrix | pytest full project suite | memory lifecycle and feedback stats pass |
| Persona catalog/public sharing | pytest full project suite | drafts, public catalog, publish/unpublish and isolation pass |
| Persona creation/files/web research | pytest full project suite | upload, parse, DeepSeek guard, mock web research pass |
| Document reader/OCR probes | pytest and check_backends | basic parse pass; optional OCR runtime availability recorded |
| Deployment/release/security | deployment tests, AST parse, export check, secret scan | scripts parse, dry-run install and fixture uninstall pass, export is sanitized, secret scan passes |
| Frontend | npm build and screenshots | TypeScript/Vite build pass; key pages captured |

Statuses in `manifest.json`: PASS means verified, FAIL means code or deterministic check failed, SKIPPED means missing optional external dependency, GAP means API/feature is not present in this branch.
"@
  $matrix | Set-Content -LiteralPath (Join-Path $ArtifactDir "TEST_MATRIX.md") -Encoding utf8
}

function Complete-Results {
  $hardFailures = @($script:Results | Where-Object { $_.status -eq "FAIL" })
  $status = if ($hardFailures.Count -eq 0) { "PASS" } else { "FAIL" }
  $manifest = [PSCustomObject]@{
    status = $status
    project_root = $ProjectRoot
    artifact_dir = $ArtifactDir
    branch = (& git branch --show-current)
    commit = (& git rev-parse --short HEAD)
    generated_at = (Get-Date).ToString("o")
    results = $script:Results
  }
  Write-JsonFile (Join-Path $ArtifactDir "manifest.json") $manifest
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add("# Full Project Evidence Results") | Out-Null
  $lines.Add("") | Out-Null
  $lines.Add("- Overall status: **$status**") | Out-Null
  $lines.Add(("- Branch: ``{0}``" -f $manifest.branch)) | Out-Null
  $lines.Add(("- Commit: ``{0}``" -f $manifest.commit)) | Out-Null
  $lines.Add(("- Artifact directory: ``{0}``" -f $ArtifactDir)) | Out-Null
  $lines.Add("") | Out-Null
  $lines.Add("| Check | Status | Evidence | Notes |") | Out-Null
  $lines.Add("| --- | --- | --- | --- |") | Out-Null
  foreach ($result in $script:Results) {
    $relativeEvidence = $result.evidence
    try {
      $relativeEvidence = Resolve-Path -LiteralPath $result.evidence -Relative
    } catch {
    }
    $lines.Add((
      "| {0} | {1} | `{2}` | {3} |" -f $result.name, $result.status, $relativeEvidence, $result.notes
    )) | Out-Null
  }
  $lines | Set-Content -LiteralPath (Join-Path $ArtifactDir "RESULTS.md") -Encoding utf8
}

try {
  Update-SecretValues
  New-TestMatrix

  $envReport = [PSCustomObject]@{
    generated_at = (Get-Date).ToString("o")
    project_root = $ProjectRoot
    artifact_dir = $ArtifactDir
    branch = (& git branch --show-current)
    commit = (& git rev-parse --short HEAD)
    git_status = (& git status --short)
    commands = @("uv", "node", "npm", "git", "ollama", "pwsh", "powershell") | ForEach-Object { Test-CommandPresence $_ }
    env_presence = @(
      "PERSONA_RAG_DEEPSEEK_API_KEY",
      "PERSONA_RAG_OLLAMA_BASE_URL",
      "PERSONA_RAG_WEB_RESEARCH_ENABLED",
      "PERSONA_RAG_SMTP_HOST",
      "PERSONA_RAG_SMTP_USERNAME",
      "PERSONA_RAG_SMTP_PASSWORD",
      "PERSONA_RAG_IMAP_HOST",
      "PERSONA_RAG_IMAP_PORT",
      "DOCUMENT_READER_ENABLE_PADDLEOCR_VL",
      "DOCUMENT_READER_ENABLE_MARKER_SURYA"
    ) | ForEach-Object {
      $value = [Environment]::GetEnvironmentVariable($_)
      [PSCustomObject]@{ key = $_; present = -not [string]::IsNullOrWhiteSpace($value); length = if ($value) { $value.Length } else { 0 } }
    }
  }
  Write-JsonFile (Join-Path $ArtifactDir "environment.json") $envReport
  Add-Result "environment_snapshot" "PASS" 0 (Join-Path $ArtifactDir "environment.json") "Secrets are recorded as presence/length only."

  Invoke-EvidenceCommand -Name "pytest_full_project" -ScriptBlock { uv run pytest -q }
  Invoke-EvidenceCommand -Name "ruff_check" -ScriptBlock { uv run ruff check app tests scripts }
  if (-not $SkipFrontend) {
    Invoke-EvidenceCommand -Name "frontend_build" -WorkingDirectory (Join-Path $ProjectRoot "app\frontend") -ScriptBlock { npm run build }
  } else {
    Add-Result "frontend_build" "SKIPPED" 0 "" "Skipped by -SkipFrontend."
  }
  Invoke-EvidenceCommand -Name "powershell_ast_parse" -ScriptBlock {
    $paths = @(
      "bootstrap.ps1",
      "install.ps1",
      "scripts/deploy/windows_local_gui_deploy.ps1",
      "scripts/deploy/windows_uninstall.ps1"
    )
    $totalErrors = 0
    foreach ($path in $paths) {
      $tokens = $null
      $errors = $null
      $resolved = (Resolve-Path $path).Path
      $source = [System.IO.File]::ReadAllText($resolved, [System.Text.Encoding]::UTF8)
      [System.Management.Automation.Language.Parser]::ParseInput($source, $resolved, [ref]$tokens, [ref]$errors) | Out-Null
      [PSCustomObject]@{ path = $path; errors = $errors.Count; messages = @($errors | ForEach-Object { $_.Message }) } | ConvertTo-Json -Compress
      $totalErrors += $errors.Count
    }
    if ($totalErrors -gt 0) { exit 1 }
  }
  $branchName = (& git branch --show-current)
  Invoke-EvidenceCommand -Name "install_dry_run_no_gui" -ScriptBlock {
    powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 `
      -Repo "yushugulao/Web_Virtual_Persona" `
      -Branch $branchName `
      -DryRun `
      -NoGui `
      -Destination $DeployTestDir
  }
  Invoke-EvidenceCommand -Name "uninstall_fixture" -ScriptBlock {
    $artifactFull = [System.IO.Path]::GetFullPath($ArtifactDir)
    $fixtureFull = [System.IO.Path]::GetFullPath($UninstallFixtureDir)
    if (-not $fixtureFull.StartsWith($artifactFull, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Uninstall fixture must stay under artifact dir: $fixtureFull"
    }
    if (Test-Path -LiteralPath $fixtureFull) {
      Remove-Item -LiteralPath $fixtureFull -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path `
      (Join-Path $fixtureFull "app\frontend"), `
      (Join-Path $fixtureFull "scripts\deploy") | Out-Null
    "fixture" | Set-Content -LiteralPath (Join-Path $fixtureFull "pyproject.toml") -Encoding utf8
    "{}" | Set-Content -LiteralPath (Join-Path $fixtureFull "app\frontend\package.json") -Encoding utf8
    "fixture" | Set-Content -LiteralPath (Join-Path $fixtureFull "scripts\deploy\README.txt") -Encoding utf8
    $manifestPath = Join-Path $ArtifactDir "uninstall-fixture-manifest.json"
    Write-JsonFile $manifestPath ([PSCustomObject]@{
      project_root = $fixtureFull
      dependencies = [PSCustomObject]@{
        uv = [PSCustomObject]@{ installed_by_deployer = $false; was_present_before = $true }
        node = [PSCustomObject]@{ installed_by_deployer = $false; was_present_before = $true }
        ollama = [PSCustomObject]@{ installed_by_deployer = $false; was_present_before = $true }
      }
    })
    $sourceUninstaller = Join-Path $ProjectRoot "scripts\deploy\windows_uninstall.ps1"
    $uninstallerCopy = Join-Path $ArtifactDir "windows_uninstall.utf8bom.ps1"
    $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $utf8Bom = New-Object System.Text.UTF8Encoding($true)
    $uninstallerText = [System.IO.File]::ReadAllText($sourceUninstaller, $strictUtf8).TrimStart([char]0xFEFF)
    [System.IO.File]::WriteAllText($uninstallerCopy, $uninstallerText, $utf8Bom)
    powershell -NoProfile -ExecutionPolicy Bypass -File $uninstallerCopy `
      -ProjectRoot $fixtureFull `
      -ManifestPath $manifestPath `
      -AssumeYes
    if (Test-Path -LiteralPath $fixtureFull) {
      throw "Uninstall fixture directory still exists: $fixtureFull"
    }
    "Uninstall fixture removed and dependencies were marked pre-existing."
  }
  Invoke-EvidenceCommand -Name "encoding_check" -ScriptBlock { uv run python scripts/dev/check_encoding.py }
  Invoke-EvidenceCommand -Name "secret_scan" -ScriptBlock { uv run python scripts/security/scan_secrets.py --tracked --fail-on-high }
  if (-not $SkipPublicExport) {
    Invoke-EvidenceCommand -Name "create_public_export" -ScriptBlock { uv run python scripts/release/create_public_export.py --output $PublicExportDir }
    Invoke-EvidenceCommand -Name "public_export_security_check" -ScriptBlock { uv run python scripts/security/prepare_public_export_check.py $PublicExportDir }
  } else {
    Add-Result "public_export" "SKIPPED" 0 "" "Skipped by -SkipPublicExport."
  }
  Invoke-EvidenceCommand -Name "document_reader_backends" -Required $false -ScriptBlock { uv run python scripts/document_reader/check_backends.py --json }
  Invoke-EvidenceCommand -Name "ollama_list" -Required $false -ScriptBlock { ollama list }
  Invoke-EvidenceCommand -Name "ollama_http_tags" -Required $false -ScriptBlock {
    try {
      $response = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 5
      $response.Content
    } catch {
      Write-Host "Ollama HTTP probe unavailable: $($_.Exception.Message)"
      exit 2
    }
  }
  Invoke-EvidenceCommand -Name "external_live_checks" -ScriptBlock {
    uv run python scripts/tests/live_external_checks.py --artifact-dir $ArtifactDir
  }

  $optional = [PSCustomObject]@{
    deepseek_live = if ([string]::IsNullOrWhiteSpace($env:PERSONA_RAG_DEEPSEEK_API_KEY)) { "SKIPPED: PERSONA_RAG_DEEPSEEK_API_KEY missing" } else { "CONFIGURED: see api/live_external_checks.json" }
    smtp_live = if ([string]::IsNullOrWhiteSpace($env:PERSONA_RAG_SMTP_HOST)) { "SKIPPED: PERSONA_RAG_SMTP_HOST missing" } else { "CONFIGURED: see api/live_external_checks.json" }
    email_qq_source_api = "IMPLEMENTED: /user-personas/{persona_id}/email/import and /user-personas/{persona_id}/qq/import"
    isolated_deploy_dir = $DeployTestDir
    screenshots_dir = $ScreenshotDir
  }
  Write-JsonFile (Join-Path $ArtifactDir "optional_live_dependencies.json") $optional
  Add-Result "optional_live_dependencies" "PASS" 0 (Join-Path $ArtifactDir "optional_live_dependencies.json") "Missing optional external services are explicit SKIPPED/GAP records."

  Complete-Results
  Write-Host ""
  Write-Host "Evidence complete: $ArtifactDir"
} catch {
  Add-Result "runner_exception" "FAIL" 1 (Join-Path $ArtifactDir "RESULTS.md") (Redact-Text $_.Exception.Message)
  Complete-Results
  throw
}

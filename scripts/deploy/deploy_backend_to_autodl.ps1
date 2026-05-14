param(
  [string]$AutodlHost = "connect.bjb2.seetacloud.com",
  [int]$AutodlPort = 25163,
  [string]$AutodlUser = "root",
  [string]$IdentityFile = "secrets\autodl_backend\autodl_backend_ed25519",
  [string]$RemoteAppDir = "/opt/web-avatar/backend",
  [string]$Profile = "standard_gpu",
  [string]$PublicUrl = "",
  [switch]$SkipModelPull,
  [switch]$SkipExport,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$identityPath = if ([System.IO.Path]::IsPathRooted($IdentityFile)) {
  $IdentityFile
} else {
  Join-Path $projectRoot $IdentityFile
}
if (-not $DryRun -and -not (Test-Path -LiteralPath $identityPath)) {
  throw "Missing AutoDL SSH key: $identityPath. Run scripts\deploy\bootstrap_autodl_backend.ps1 first."
}

$stateDir = Join-Path $projectRoot ".deploy\autodl"
$logDir = Join-Path $stateDir "logs"
New-Item -ItemType Directory -Force -Path $stateDir, $logDir | Out-Null

$exportDir = Join-Path $stateDir "public-export"
$bundlePath = Join-Path $stateDir "web-avatar-backend-public-export.tar.gz"
$remoteEnvPath = Join-Path $stateDir "remote.env"
$remoteScriptPath = Join-Path $stateDir "remote_backend_deploy.sh"
$adminCredsPath = Join-Path $stateDir "admin_credentials.txt"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Read-DotEnv {
  param([string]$Path)
  $values = @{}
  if (-not (Test-Path -LiteralPath $Path)) {
    return $values
  }
  foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
      continue
    }
    $key, $value = $trimmed.Split("=", 2)
    $values[$key.Trim()] = $value.Trim()
  }
  return $values
}

function New-Password {
  $bytes = New-Object byte[] 24
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "A").Replace("/", "b")
}

function Get-AdminPassword {
  if ($env:PERSONA_RAG_AUTODL_ADMIN_PASSWORD) {
    return $env:PERSONA_RAG_AUTODL_ADMIN_PASSWORD
  }
  if (Test-Path -LiteralPath $adminCredsPath) {
    $line = Get-Content -LiteralPath $adminCredsPath -Encoding UTF8 | Where-Object { $_ -like "password=*" } | Select-Object -First 1
    if ($line) {
      return $line.Split("=", 2)[1]
    }
  }
  $password = New-Password
  if (-not $DryRun) {
    @(
      "# Local-only generated AutoDL admin credentials. Do not commit.",
      "username=admin",
      "password=$password"
    ) | Set-Content -LiteralPath $adminCredsPath -Encoding UTF8
  }
  return $password
}

function Get-ProfileData {
  $profilePath = Join-Path $projectRoot "configs\deployment_profiles\$Profile.json"
  if (-not (Test-Path -LiteralPath $profilePath)) {
    throw "Unknown deployment profile: $Profile"
  }
  return Get-Content -LiteralPath $profilePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-RemoteEnv {
  $profileData = Get-ProfileData
  $localEnv = Read-DotEnv (Join-Path $projectRoot ".env")
  $adminPassword = Get-AdminPassword
  $envMap = [ordered]@{
    "PERSONA_RAG_DEPLOYMENT_MODE" = "frp_tunnel_autodl_backend"
    "PERSONA_RAG_DEPLOYMENT_PROFILE" = $Profile
    "PERSONA_RAG_AUTH_REQUIRED" = "true"
    "PERSONA_RAG_AUTH_TRUST_PROXY_HEADERS" = "true"
    "PERSONA_RAG_AUTH_ADMIN_USERNAME" = "admin"
    "PERSONA_RAG_AUTH_ADMIN_EMAIL" = "admin@web-avatar.local"
    "PERSONA_RAG_AUTH_ADMIN_PASSWORD" = $adminPassword
    "PERSONA_RAG_AUTH_CHALLENGE_REQUIRED" = "true"
    "PERSONA_RAG_AUTH_CHALLENGE_MODE" = "slider"
    "PERSONA_RAG_MODEL_PROVIDER" = "ollama"
    "PERSONA_RAG_OLLAMA_BASE_URL" = "http://127.0.0.1:11434"
    "PERSONA_RAG_SQLITE_PATH" = "data/sqlite/persona_rag.sqlite3"
    "PERSONA_RAG_VECTOR_INDEX_PATH" = "data/indexes/dense_qwen3_embedding_0_6b.json"
    "PERSONA_RAG_PUBLIC_URL" = $PublicUrl
  }
  foreach ($property in $profileData.env.PSObject.Properties) {
    $envMap[$property.Name] = [string]$property.Value
  }
  foreach ($key in @(
    "PERSONA_RAG_DEEPSEEK_API_KEY",
    "PERSONA_RAG_SMTP_HOST",
    "PERSONA_RAG_SMTP_PORT",
    "PERSONA_RAG_SMTP_SECURITY",
    "PERSONA_RAG_SMTP_USERNAME",
    "PERSONA_RAG_SMTP_PASSWORD",
    "PERSONA_RAG_SMTP_FROM"
  )) {
    $value = [Environment]::GetEnvironmentVariable($key)
    if (-not $value -and $localEnv.ContainsKey($key)) {
      $value = $localEnv[$key]
    }
    if ($value) {
      $envMap[$key] = $value
    }
  }
  $lines = @(
    "# Generated for AutoDL backend deployment.",
    "# Keep this file local and remote-only. Do not commit secrets."
  )
  foreach ($key in $envMap.Keys) {
    $lines += "$key=$($envMap[$key])"
  }
  if (-not $DryRun) {
    $lines | Set-Content -LiteralPath $remoteEnvPath -Encoding UTF8
  }
  return $profileData
}

function Write-RemoteScript {
  param([object]$ProfileData)
  $models = @($ProfileData.models) -join " "
  $pullModels = if ($SkipModelPull) { "0" } else { "1" }
  $script = @"
#!/usr/bin/env bash
set -euo pipefail

REMOTE_APP_DIR="$RemoteAppDir"
BUNDLE="/tmp/web-avatar-backend-public-export.tar.gz"
REMOTE_ENV="/tmp/web-avatar-backend.env"
PULL_MODELS="$pullModels"
MODELS="$models"

log() {
  printf '\n==> %s\n' "`$1"
}

ensure_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y curl ca-certificates git tar gzip unzip procps lsof
  fi
}

ensure_uv() {
  export PATH="`$HOME/.local/bin:`$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="`$HOME/.local/bin:`$PATH"
  fi
  uv --version
}

ensure_ollama() {
  if ! command -v ollama >/dev/null 2>&1; then
    for i in `$(seq 1 5); do
      if curl -fsSL --retry 5 --retry-delay 5 --connect-timeout 20 https://ollama.com/install.sh -o /tmp/install_ollama.sh; then
        bash /tmp/install_ollama.sh
        break
      fi
      echo "Ollama install script download failed, retry `$i/5." >&2
      sleep 5
    done
    if ! command -v ollama >/dev/null 2>&1; then
      echo "Ollama installation failed after retries." >&2
      return 1
    fi
  fi
  mkdir -p "`$REMOTE_APP_DIR/models/ollama" "`$REMOTE_APP_DIR/models/logs"
  export OLLAMA_MODELS="`$REMOTE_APP_DIR/models/ollama"
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    if [ -f "`$REMOTE_APP_DIR/.deploy/autodl/ollama.pid" ]; then
      old_pid="`$(cat "`$REMOTE_APP_DIR/.deploy/autodl/ollama.pid" || true)"
      if [ -n "`$old_pid" ]; then kill "`$old_pid" >/dev/null 2>&1 || true; fi
    fi
    nohup env OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS="`$OLLAMA_MODELS" ollama serve \
      >"`$REMOTE_APP_DIR/models/logs/ollama.out.log" 2>"`$REMOTE_APP_DIR/models/logs/ollama.err.log" &
    echo `$! > "`$REMOTE_APP_DIR/.deploy/autodl/ollama.pid"
  fi
  for i in `$(seq 1 90); do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Ollama did not become healthy." >&2
  tail -120 "`$REMOTE_APP_DIR/models/logs/ollama.err.log" || true
  return 1
}

pull_models() {
  if [ "`$PULL_MODELS" != "1" ]; then
    log "Skipping model pulls"
    return 0
  fi
  export OLLAMA_MODELS="`$REMOTE_APP_DIR/models/ollama"
  for model in `$MODELS; do
    log "Pulling model `$model"
    ollama pull "`$model"
  done
  ollama list
}

unpack_app() {
  mkdir -p "`$REMOTE_APP_DIR" "`$REMOTE_APP_DIR/.deploy/autodl" "`$REMOTE_APP_DIR/logs" \
    "`$REMOTE_APP_DIR/data/sqlite" "`$REMOTE_APP_DIR/data/indexes" "`$REMOTE_APP_DIR/data/logs" \
    "`$REMOTE_APP_DIR/data/runtime_logs" "`$REMOTE_APP_DIR/models/ollama"
  find "`$REMOTE_APP_DIR" -mindepth 1 -maxdepth 1 \
    ! -name ".env" ! -name ".deploy" ! -name "data" ! -name "models" ! -name "logs" \
    -exec rm -rf {} +
  tar -xzf "`$BUNDLE" -C "`$REMOTE_APP_DIR"
  tr -d '\r' < "`$REMOTE_ENV" > "`$REMOTE_APP_DIR/.env"
}

install_app() {
  cd "`$REMOTE_APP_DIR"
  export PATH="`$HOME/.local/bin:`$PATH"
  uv sync --extra dev
}

start_backend() {
  cd "`$REMOTE_APP_DIR"
  if [ -f .deploy/autodl/backend.pid ]; then
    old_pid="`$(cat .deploy/autodl/backend.pid || true)"
    if [ -n "`$old_pid" ]; then kill "`$old_pid" >/dev/null 2>&1 || true; fi
  fi
  set -a
  . ./.env
  set +a
  nohup uv run uvicorn app.backend.main:app --host 127.0.0.1 --port 8001 \
    >logs/backend.out.log 2>logs/backend.err.log &
  echo `$! > .deploy/autodl/backend.pid
  for i in `$(seq 1 90); do
    if curl -fsS http://127.0.0.1:8001/health >/dev/null 2>&1; then
      curl -fsS http://127.0.0.1:8001/health
      return 0
    fi
    sleep 2
  done
  echo "Backend did not become healthy." >&2
  tail -160 logs/backend.err.log || true
  return 1
}

log "Installing system prerequisites"
ensure_packages
log "Installing uv"
ensure_uv
log "Deploying application files"
unpack_app
log "Installing Python dependencies"
install_app
log "Installing and starting Ollama"
ensure_ollama
pull_models
log "Starting backend"
start_backend
log "AutoDL backend deployment complete"
"@
  if (-not $DryRun) {
    $script | Set-Content -LiteralPath $remoteScriptPath -Encoding UTF8
  }
}

function Invoke-Remote {
  param([string]$Command)
  if ($DryRun) {
    Write-Host "DRY RUN ssh: $Command"
    return
  }
  & ssh -p $AutodlPort -i $identityPath -o StrictHostKeyChecking=accept-new "$AutodlUser@$AutodlHost" $Command
  if ($LASTEXITCODE -ne 0) {
    throw "Remote command failed: $Command"
  }
}

Write-Step "Creating sanitized backend export"
if (-not $SkipExport) {
  if (-not $DryRun) {
    uv run python scripts\release\create_public_export.py --output $exportDir
  } else {
    Write-Host "DRY RUN: would create public export at $exportDir"
  }
}

if (-not $DryRun) {
  if (Test-Path -LiteralPath $bundlePath) { Remove-Item -LiteralPath $bundlePath -Force }
  tar -C $exportDir -czf $bundlePath .
} else {
  Write-Host "DRY RUN: would pack $exportDir into $bundlePath"
}

$profileData = Write-RemoteEnv
Write-RemoteScript -ProfileData $profileData

Write-Step "Uploading backend bundle to AutoDL"
if ($DryRun) {
  Write-Host "DRY RUN: would upload bundle/env/script to $AutodlUser@$AutodlHost"
} else {
  scp -P $AutodlPort -i $identityPath -o StrictHostKeyChecking=accept-new $bundlePath "$AutodlUser@${AutodlHost}:/tmp/web-avatar-backend-public-export.tar.gz"
  scp -P $AutodlPort -i $identityPath -o StrictHostKeyChecking=accept-new $remoteEnvPath "$AutodlUser@${AutodlHost}:/tmp/web-avatar-backend.env"
  scp -P $AutodlPort -i $identityPath -o StrictHostKeyChecking=accept-new $remoteScriptPath "$AutodlUser@${AutodlHost}:/tmp/web-avatar-backend-deploy.sh"
}

Write-Step "Running AutoDL backend deployment"
Invoke-Remote "chmod +x /tmp/web-avatar-backend-deploy.sh && bash /tmp/web-avatar-backend-deploy.sh"

Write-Host "AutoDL backend is healthy at remote 127.0.0.1:8001." -ForegroundColor Green
Write-Host "Admin credentials are stored locally at $adminCredsPath" -ForegroundColor Yellow

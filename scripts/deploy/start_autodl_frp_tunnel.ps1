param(
  [string]$AutodlHost = $env:PERSONA_RAG_AUTODL_HOST,
  [int]$AutodlPort = $(if ($env:PERSONA_RAG_AUTODL_PORT) { [int]$env:PERSONA_RAG_AUTODL_PORT } else { 22 }),
  [string]$AutodlUser = "root",
  [string]$IdentityFile = "secrets\autodl_backend\autodl_backend_ed25519",
  [string]$ServerHost = $env:PERSONA_RAG_PUBLIC_SERVER_HOST,
  [int]$ServerPort = 7000,
  [int]$RemotePort = 18001,
  [string]$RemoteAppDir = "/opt/web-avatar/backend",
  [string]$KeyDir = "secrets\public_tunnel",
  [string]$FrpVersion = "0.68.0",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ServerHost)) {
  throw "Pass -ServerHost <public-ip-or-domain>, or set PERSONA_RAG_PUBLIC_SERVER_HOST."
}
if ([string]::IsNullOrWhiteSpace($AutodlHost)) {
  throw "Pass -AutodlHost <AUTODL_SSH_HOST>, or set PERSONA_RAG_AUTODL_HOST."
}

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

$frpTokenPath = Join-Path (Join-Path $projectRoot $KeyDir) "frp_token.txt"
if (-not (Test-Path -LiteralPath $frpTokenPath)) {
  throw "Missing $frpTokenPath. Run scripts\deploy\bootstrap_public_ecs_frp.ps1 first so client and server share one frp token."
}
$frpToken = (Get-Content -LiteralPath $frpTokenPath -Raw).Trim()

$stateDir = Join-Path $projectRoot ".deploy\autodl"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$remoteScriptPath = Join-Path $stateDir "remote_start_frpc.sh"
$remoteConfigPath = Join-Path $stateDir "frpc-web-avatar-autodl.toml"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Remote {
  param([string]$Command)
  if ($DryRun) {
    Write-Host "DRY RUN ssh: $Command"
    return ""
  }
  $output = & ssh -p $AutodlPort -i $identityPath -o StrictHostKeyChecking=accept-new "$AutodlUser@$AutodlHost" $Command
  if ($LASTEXITCODE -ne 0) {
    throw "Remote command failed: $Command"
  }
  return ($output -join "`n")
}

$config = (Get-Content -LiteralPath (Join-Path $projectRoot "deploy\public\frpc-web-avatar.toml.example") -Raw).
  Replace("serverAddr = `"<PUBLIC_SERVER_IP>`"", "serverAddr = `"$ServerHost`"").
  Replace("serverPort = 7000", "serverPort = $ServerPort").
  Replace("__FRP_TOKEN__", $frpToken).
  Replace("localIP = `"127.0.0.1`"", "localIP = `"127.0.0.1`"").
  Replace("localPort = 8001", "localPort = 8001").
  Replace("remotePort = 18001", "remotePort = $RemotePort")

if (-not $DryRun) {
  $config | Set-Content -LiteralPath $remoteConfigPath -Encoding ASCII
}

$script = @"
#!/usr/bin/env bash
set -euo pipefail

REMOTE_APP_DIR="$RemoteAppDir"
FRP_VERSION="$FrpVersion"
FRP_ROOT="`$REMOTE_APP_DIR/.deploy/frp"
CONFIG_SRC="/tmp/frpc-web-avatar-autodl.toml"
CONFIG_DST="`$REMOTE_APP_DIR/.deploy/autodl/frpc-web-avatar.toml"
LOG_DIR="`$REMOTE_APP_DIR/logs"

mkdir -p "`$FRP_ROOT" "`$REMOTE_APP_DIR/.deploy/autodl" "`$LOG_DIR"

for i in `$(seq 1 60); do
  if curl -fsS http://127.0.0.1:8001/health >/dev/null 2>&1; then
    break
  fi
  if [ "`$i" -eq 60 ]; then
    echo "AutoDL backend is not healthy at 127.0.0.1:8001 after waiting." >&2
    tail -80 "`$LOG_DIR/backend.err.log" || true
    exit 1
  fi
  sleep 1
done

if [ ! -x "`$FRP_ROOT/frpc" ]; then
  arch="`$(uname -m)"
  case "`$arch" in
    x86_64|amd64) frp_arch="amd64" ;;
    aarch64|arm64) frp_arch="arm64" ;;
    *) echo "Unsupported Linux architecture for frp: `$arch" >&2; exit 1 ;;
  esac
  package="frp_`${FRP_VERSION}_linux_`${frp_arch}.tar.gz"
  url="https://github.com/fatedier/frp/releases/download/v`${FRP_VERSION}/`${package}"
  tmp="/tmp/`$package"
  curl -L --retry 3 --retry-delay 3 -o "`$tmp" "`$url"
  rm -rf "`$FRP_ROOT/extract"
  mkdir -p "`$FRP_ROOT/extract"
  tar -xzf "`$tmp" -C "`$FRP_ROOT/extract"
  found="`$(find "`$FRP_ROOT/extract" -type f -name frpc | head -n 1)"
  if [ -z "`$found" ]; then
    echo "Downloaded frp package, but frpc was not found." >&2
    exit 1
  fi
  cp "`$found" "`$FRP_ROOT/frpc"
  chmod +x "`$FRP_ROOT/frpc"
fi

cp "`$CONFIG_SRC" "`$CONFIG_DST"
"`$FRP_ROOT/frpc" verify -c "`$CONFIG_DST"

if [ -f "`$REMOTE_APP_DIR/.deploy/autodl/frpc.pid" ]; then
  old_pid="`$(cat "`$REMOTE_APP_DIR/.deploy/autodl/frpc.pid" || true)"
  if [ -n "`$old_pid" ]; then kill "`$old_pid" >/dev/null 2>&1 || true; fi
fi

nohup "`$FRP_ROOT/frpc" -c "`$CONFIG_DST" >"`$LOG_DIR/frpc.out.log" 2>"`$LOG_DIR/frpc.err.log" &
echo `$! > "`$REMOTE_APP_DIR/.deploy/autodl/frpc.pid"

for i in `$(seq 1 50); do
  if grep -q "start proxy success" "`$LOG_DIR/frpc.out.log" 2>/dev/null; then
    tail -40 "`$LOG_DIR/frpc.out.log"
    exit 0
  fi
  if grep -qi "login to the server failed\|session shutdown\|authentication failed" "`$LOG_DIR/frpc.out.log" "`$LOG_DIR/frpc.err.log" 2>/dev/null; then
    tail -120 "`$LOG_DIR/frpc.out.log" || true
    tail -120 "`$LOG_DIR/frpc.err.log" || true
    exit 1
  fi
  sleep 1
done

echo "Timed out waiting for frpc readiness." >&2
tail -120 "`$LOG_DIR/frpc.out.log" || true
tail -120 "`$LOG_DIR/frpc.err.log" || true
exit 1
"@

if (-not $DryRun) {
  $script | Set-Content -LiteralPath $remoteScriptPath -Encoding UTF8
}

Write-Step "Uploading AutoDL frpc config"
if ($DryRun) {
  Write-Host "DRY RUN: would upload frpc config/script to AutoDL."
} else {
  scp -P $AutodlPort -i $identityPath -o StrictHostKeyChecking=accept-new $remoteConfigPath "$AutodlUser@${AutodlHost}:/tmp/frpc-web-avatar-autodl.toml"
  scp -P $AutodlPort -i $identityPath -o StrictHostKeyChecking=accept-new $remoteScriptPath "$AutodlUser@${AutodlHost}:/tmp/start-web-avatar-frpc.sh"
}

Write-Step "Starting AutoDL frpc tunnel"
Invoke-Remote "chmod +x /tmp/start-web-avatar-frpc.sh && bash /tmp/start-web-avatar-frpc.sh"

Write-Host "AutoDL frpc tunnel is connected: ECS 127.0.0.1:$RemotePort -> AutoDL 127.0.0.1:8001" -ForegroundColor Green

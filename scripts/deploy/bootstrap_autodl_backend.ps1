param(
  [string]$AutodlHost = $env:PERSONA_RAG_AUTODL_HOST,
  [int]$AutodlPort = $(if ($env:PERSONA_RAG_AUTODL_PORT) { [int]$env:PERSONA_RAG_AUTODL_PORT } else { 22 }),
  [string]$AutodlUser = "root",
  [string]$KeyDir = "secrets\autodl_backend",
  [string]$IdentityFile = "",
  [string]$PasswordEnvVar = "PERSONA_RAG_AUTODL_ROOT_PASSWORD",
  [string]$HostKeyFingerprint = $env:PERSONA_RAG_AUTODL_HOST_KEY_FINGERPRINT,
  [switch]$InstallKeyWithPassword,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($AutodlHost)) {
  throw "Pass -AutodlHost <AUTODL_SSH_HOST>, or set PERSONA_RAG_AUTODL_HOST."
}

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$keyRoot = Join-Path $projectRoot $KeyDir
New-Item -ItemType Directory -Force -Path $keyRoot | Out-Null

if (-not $IdentityFile) {
  $IdentityFile = Join-Path $keyRoot "autodl_backend_ed25519"
} elseif (-not [System.IO.Path]::IsPathRooted($IdentityFile)) {
  $IdentityFile = Join-Path $projectRoot $IdentityFile
}
$publicKeyPath = "$IdentityFile.pub"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-KeyLogin {
  if ($DryRun) {
    Write-Host "DRY RUN: would test key login to $AutodlUser@${AutodlHost}:$AutodlPort"
    return $true
  }
  if (-not (Test-Path -LiteralPath $IdentityFile)) {
    return $false
  }
  & ssh -p $AutodlPort -i $IdentityFile -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$AutodlUser@$AutodlHost" "echo autodl_key_ok" 2>$null
  return $LASTEXITCODE -eq 0
}

Write-Step "Preparing AutoDL SSH key"
if (-not (Test-Path -LiteralPath $IdentityFile)) {
  if ($DryRun) {
    Write-Host "DRY RUN: would generate SSH key at $IdentityFile"
  } else {
    ssh-keygen -t ed25519 -N "" -C "web-avatar-autodl-backend" -f $IdentityFile | Out-Null
  }
}

if (Test-KeyLogin) {
  Write-Host "AutoDL key login is ready." -ForegroundColor Green
  return
}

if (-not $InstallKeyWithPassword) {
  Write-Host "AutoDL key login is not ready." -ForegroundColor Yellow
  Write-Host "Run this script once with -InstallKeyWithPassword after setting $PasswordEnvVar in your current shell."
  Write-Host "Example: `$env:$PasswordEnvVar = '<one-time-root-password>'; .\scripts\deploy\bootstrap_autodl_backend.ps1 -InstallKeyWithPassword"
  throw "AutoDL key login required before non-interactive deployment."
}

$password = [Environment]::GetEnvironmentVariable($PasswordEnvVar)
if ([string]::IsNullOrWhiteSpace($password)) {
  throw "Set $PasswordEnvVar in the current shell before using -InstallKeyWithPassword. The value is not written to disk."
}

$plink = Get-Command plink -ErrorAction SilentlyContinue
if (-not $plink) {
  throw "PuTTY plink was not found. Install PuTTY or add the public key manually to AutoDL ~/.ssh/authorized_keys."
}

$publicKey = (Get-Content -LiteralPath $publicKeyPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($publicKey)) {
  throw "Public key is empty: $publicKeyPath"
}

Write-Step "Installing SSH key on AutoDL"
Write-Host "Using plink once with a password from environment variable $PasswordEnvVar. The password is not stored by this script." -ForegroundColor Yellow

$remote = "$AutodlUser@$AutodlHost"
$remoteCommand = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qxF '$publicKey' ~/.ssh/authorized_keys 2>/dev/null || printf '%s\n' '$publicKey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo autodl_key_installed"

if ($DryRun) {
  Write-Host "DRY RUN: would install public key on $remote"
  return
}

$plinkArgs = @(
  "-ssh",
  "-batch",
  "-P", [string]$AutodlPort,
  "-pw", $password,
  $remote,
  $remoteCommand
)
if (-not [string]::IsNullOrWhiteSpace($HostKeyFingerprint)) {
  $plinkArgs = @(
    "-ssh",
    "-batch",
    "-P", [string]$AutodlPort,
    "-hostkey", $HostKeyFingerprint,
    "-pw", $password,
    $remote,
    $remoteCommand
  )
}
& $plink.Source @plinkArgs
if ($LASTEXITCODE -ne 0) {
  throw "Failed to install AutoDL SSH key. If this is the first PuTTY connection, set PERSONA_RAG_AUTODL_HOST_KEY_FINGERPRINT to the server fingerprint shown by plink, or install the public key manually."
}

if (-not (Test-KeyLogin)) {
  throw "Installed key, but key login still failed."
}

Write-Host "AutoDL key login is ready." -ForegroundColor Green

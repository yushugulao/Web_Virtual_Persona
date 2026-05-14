param(
  [string]$ServerHost = "<PUBLIC_SERVER_IP>",
  [string]$DeployUser = "deploy-admin",
  [string]$IdentityFile = "secrets\public_tunnel\deploy_admin_ed25519",
  [string]$RemoteFrontendDir = "/opt/web-avatar/frontend",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$identityPath = Resolve-Path -LiteralPath (Join-Path $projectRoot $IdentityFile)
$frontendRoot = Join-Path $projectRoot "app\frontend"
$distRoot = Join-Path $frontendRoot "dist"
$deployTmp = Join-Path $projectRoot ".deploy"
$bundlePath = Join-Path $deployTmp "web-avatar-frontend.tar.gz"

New-Item -ItemType Directory -Force -Path $deployTmp | Out-Null

if (-not $SkipBuild) {
  Push-Location -LiteralPath $frontendRoot
  try {
    Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
    npm run build
  } finally {
    Pop-Location
  }
}

if (-not (Test-Path -LiteralPath (Join-Path $distRoot "index.html"))) {
  throw "Frontend dist is missing. Run npm run build first."
}

if (Test-Path -LiteralPath $bundlePath) {
  Remove-Item -LiteralPath $bundlePath -Force
}

tar -C $distRoot -czf $bundlePath .

$remote = "$DeployUser@$ServerHost"
$remoteBundle = "/tmp/web-avatar-frontend.tar.gz"

scp -i $identityPath -o StrictHostKeyChecking=accept-new $bundlePath "${remote}:$remoteBundle"

$remoteCommand = @"
set -euo pipefail
sudo mkdir -p '$RemoteFrontendDir'
sudo rm -rf '$RemoteFrontendDir'/*
sudo tar -xzf '$remoteBundle' -C '$RemoteFrontendDir'
if id www-data >/dev/null 2>&1; then
  sudo chown -R www-data:www-data '$RemoteFrontendDir'
elif id nginx >/dev/null 2>&1; then
  sudo chown -R nginx:nginx '$RemoteFrontendDir'
else
  sudo chown -R root:root '$RemoteFrontendDir'
fi
rm -f '$remoteBundle'
sudo nginx -t
sudo systemctl reload nginx
echo 'Frontend published.'
"@

ssh -i $identityPath -o StrictHostKeyChecking=accept-new $remote $remoteCommand

Write-Host "Published frontend to https://$ServerHost/" -ForegroundColor Green

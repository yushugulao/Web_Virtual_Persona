param(
  [string]$ServerHost = "<PUBLIC_SERVER_IP>",
  [string]$TunnelUser = "persona-tunnel",
  [string]$IdentityFile = "secrets\public_tunnel\persona_tunnel_ed25519",
  [string]$LocalBackendHost = "127.0.0.1",
  [int]$LocalBackendPort = 8001,
  [string]$RemoteBindAddress = "127.0.0.1",
  [int]$RemotePort = 18001
)

$ErrorActionPreference = "Stop"

if ($ServerHost -eq "<PUBLIC_SERVER_IP>") {
  throw "Pass -ServerHost with your real public server IP or domain."
}

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$identityPath = Resolve-Path -LiteralPath (Join-Path $projectRoot $IdentityFile)

$backendTest = Test-NetConnection $LocalBackendHost -Port $LocalBackendPort -WarningAction SilentlyContinue
if (-not $backendTest.TcpTestSucceeded) {
  throw "Local backend is not reachable at ${LocalBackendHost}:${LocalBackendPort}. Start it first."
}

$remoteForward = "{0}:{1}:{2}:{3}" -f $RemoteBindAddress, $RemotePort, $LocalBackendHost, $LocalBackendPort
$remote = "$TunnelUser@$ServerHost"

Write-Host "Opening reverse tunnel: $remoteForward -> $remote" -ForegroundColor Cyan
Write-Host "Keep this window open while the public demo is online." -ForegroundColor Yellow

ssh `
  -i $identityPath `
  -N -T `
  -o ExitOnForwardFailure=yes `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  -o StrictHostKeyChecking=accept-new `
  -R $remoteForward `
  $remote

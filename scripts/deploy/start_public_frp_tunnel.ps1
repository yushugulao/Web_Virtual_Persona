param(
  [string]$ServerHost = "<PUBLIC_SERVER_IP>",
  [int]$ServerPort = 7000,
  [string]$LocalBackendHost = "127.0.0.1",
  [int]$LocalBackendPort = 8001,
  [int]$RemotePort = 18001,
  [string]$KeyDir = "secrets\public_tunnel",
  [string]$FrpVersion = "0.68.0",
  [string]$FrpcExe = "",
  [switch]$DownloadIfMissing
)

$ErrorActionPreference = "Stop"

if ($ServerHost -eq "<PUBLIC_SERVER_IP>") {
  throw "Pass -ServerHost with your real public server IP or domain."
}

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$keyRoot = Join-Path $projectRoot $KeyDir
$frpTokenPath = Join-Path $keyRoot "frp_token.txt"
if (-not (Test-Path -LiteralPath $frpTokenPath)) {
  throw "Missing $frpTokenPath. Run scripts\deploy\bootstrap_public_ecs_frp.ps1 first so client and server share one frp token."
}
$frpToken = (Get-Content -LiteralPath $frpTokenPath -Raw).Trim()

$backendTest = Test-NetConnection $LocalBackendHost -Port $LocalBackendPort -WarningAction SilentlyContinue
if (-not $backendTest.TcpTestSucceeded) {
  throw "Local backend is not reachable at ${LocalBackendHost}:${LocalBackendPort}. Start it first."
}

if (-not $FrpcExe) {
  $frpcRoot = Join-Path $keyRoot "frp"
  $candidate = Get-ChildItem -LiteralPath $frpcRoot -Recurse -Filter frpc.exe -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($candidate) {
    $FrpcExe = $candidate.FullName
  }
}

if (-not $FrpcExe -or -not (Test-Path -LiteralPath $FrpcExe)) {
  if (-not $DownloadIfMissing) {
    throw "frpc.exe was not found. Pass -DownloadIfMissing to download the official frp Windows amd64 release into $KeyDir\frp, or pass -FrpcExe."
  }
  $frpcRoot = Join-Path $keyRoot "frp"
  New-Item -ItemType Directory -Force -Path $frpcRoot | Out-Null
  $zipPath = Join-Path $frpcRoot "frp_${FrpVersion}_windows_amd64.zip"
  $url = "https://github.com/fatedier/frp/releases/download/v${FrpVersion}/frp_${FrpVersion}_windows_amd64.zip"
  Invoke-WebRequest -Uri $url -OutFile $zipPath
  Expand-Archive -LiteralPath $zipPath -DestinationPath $frpcRoot -Force
  $candidate = Get-ChildItem -LiteralPath $frpcRoot -Recurse -Filter frpc.exe | Select-Object -First 1
  if (-not $candidate) {
    throw "Downloaded frp package, but frpc.exe was not found."
  }
  $FrpcExe = $candidate.FullName
}

$configPath = Join-Path $keyRoot "frpc-web-avatar.toml"
$config = (Get-Content -LiteralPath (Join-Path $projectRoot "deploy\public\frpc-web-avatar.toml.example") -Raw).
  Replace("serverAddr = `"<PUBLIC_SERVER_IP>`"", "serverAddr = `"$ServerHost`"").
  Replace("serverPort = 7000", "serverPort = $ServerPort").
  Replace("__FRP_TOKEN__", $frpToken).
  Replace("localIP = `"127.0.0.1`"", "localIP = `"$LocalBackendHost`"").
  Replace("localPort = 8001", "localPort = $LocalBackendPort").
  Replace("remotePort = 18001", "remotePort = $RemotePort")
Set-Content -LiteralPath $configPath -Value $config -Encoding ascii

Write-Host "Verifying frpc config..." -ForegroundColor Cyan
& $FrpcExe verify -c $configPath
if ($LASTEXITCODE -ne 0) {
  throw "frpc config verification failed."
}

Write-Host "Opening frp tunnel: ECS 127.0.0.1:$RemotePort -> local ${LocalBackendHost}:$LocalBackendPort" -ForegroundColor Cyan
Write-Host "Keep this window open while the public demo is online." -ForegroundColor Yellow
& $FrpcExe -c $configPath

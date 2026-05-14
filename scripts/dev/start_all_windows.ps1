param(
  [string]$HostAddress = "127.0.0.1",
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $ProjectRoot

Write-Host "Starting backend on http://$HostAddress`:$BackendPort"
$backend = Start-Process powershell `
  -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", "scripts\dev\start_backend.ps1", "-HostAddress", $HostAddress, "-Port", "$BackendPort") `
  -WorkingDirectory $ProjectRoot `
  -PassThru

Write-Host "Starting frontend on http://127.0.0.1:$FrontendPort"
$frontendArgs = "cd '$ProjectRoot\app\frontend'; `$env:VITE_API_BASE_URL='http://$HostAddress`:$BackendPort'; npm run dev -- --host 127.0.0.1 --port $FrontendPort"
$frontend = Start-Process powershell `
  -ArgumentList @("-NoExit", "-Command", $frontendArgs) `
  -WorkingDirectory $ProjectRoot `
  -PassThru

Write-Host "Started processes: backend=$($backend.Id), frontend=$($frontend.Id)"
Write-Host "Close the spawned terminals to stop the services."


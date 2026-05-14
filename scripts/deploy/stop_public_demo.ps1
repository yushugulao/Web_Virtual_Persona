param(
  [string]$LocalBackendHost = "127.0.0.1",
  [int]$LocalBackendPort = 8001,
  [int]$RemotePort = 18001,
  [switch]$StopBackend
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

Write-Host "Stopping local frpc public tunnel processes..." -ForegroundColor Cyan
Get-Process frpc -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "Stopping frpc PID $($_.Id)"
  Stop-Process -Id $_.Id -Force
}

Write-Host "Stopping reverse SSH public tunnel processes..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "name='ssh.exe'" -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -and (
      $_.CommandLine -match "-R\s+127\.0\.0\.1:${RemotePort}:${LocalBackendHost}:$LocalBackendPort" -or
      $_.CommandLine -match "127\.0\.0\.1:${RemotePort}:${LocalBackendHost}:$LocalBackendPort"
    )
  } |
  ForEach-Object {
    Write-Host "Stopping reverse SSH PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force
  }

if ($StopBackend) {
  Write-Host "Stopping local backend listener on ${LocalBackendHost}:${LocalBackendPort}..." -ForegroundColor Cyan
  Get-NetTCPConnection -LocalAddress $LocalBackendHost -LocalPort $LocalBackendPort -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" -and $_.OwningProcess -ne 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
      Write-Host "Stopping backend PID $_"
      Stop-Process -Id $_ -Force
    }
}

Start-Sleep -Seconds 1

$remainingFrpc = @(Get-Process frpc -ErrorAction SilentlyContinue)
$remainingReverseSsh = @(
  Get-CimInstance Win32_Process -Filter "name='ssh.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -and (
        $_.CommandLine -match "-R\s+127\.0\.0\.1:${RemotePort}:${LocalBackendHost}:$LocalBackendPort" -or
        $_.CommandLine -match "127\.0\.0\.1:${RemotePort}:${LocalBackendHost}:$LocalBackendPort"
      )
    }
)

if ($remainingFrpc.Count -eq 0 -and $remainingReverseSsh.Count -eq 0) {
  Write-Host "Public backend tunnel is stopped. Nginx may still serve the static frontend, but API回源 is offline until deployment restarts frpc." -ForegroundColor Green
} else {
  Write-Host "Some tunnel processes are still present; inspect them manually." -ForegroundColor Yellow
}

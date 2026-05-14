param(
  [string]$ServerHost = $env:PERSONA_RAG_PUBLIC_SERVER_HOST,
  [string]$DeployUser = "deploy-admin",
  [string]$IdentityFile = "secrets\public_tunnel\deploy_admin_ed25519",
  [string]$LocalBackendHost = "127.0.0.1",
  [int]$LocalBackendPort = 8001,
  [int]$RemotePort = 18001,
  [int]$FrpServerPort = 7000,
  [switch]$SkipBuild,
  [switch]$SkipFrontendPublish,
  [switch]$SkipBackendStart,
  [switch]$SkipRemoteFrpsCheck,
  [switch]$KeepExistingTunnels
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ServerHost)) {
  throw "Pass -ServerHost <public-ip-or-domain>, or set PERSONA_RAG_PUBLIC_SERVER_HOST."
}

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$logDir = Join-Path $projectRoot ".deploy\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$backendOut = Join-Path $logDir "backend_${LocalBackendPort}.out.log"
$backendErr = Join-Path $logDir "backend_${LocalBackendPort}.err.log"
$frpcOut = Join-Path $logDir "frpc_public.out.log"
$frpcErr = Join-Path $logDir "frpc_public.err.log"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-HttpOk {
  param(
    [string]$Uri,
    [int]$TimeoutSec = 5,
    [switch]$SkipCertificateCheck
  )
  try {
    if ($SkipCertificateCheck) {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec $TimeoutSec -SkipCertificateCheck
    } else {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec $TimeoutSec
    }
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
  } catch {
    return $false
  }
}

function Wait-HttpOk {
  param(
    [string]$Uri,
    [int]$TimeoutSec = 90,
    [int]$AttemptTimeoutSec = 8,
    [switch]$SkipCertificateCheck
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $lastFailure = "not attempted"

  while ((Get-Date) -lt $deadline) {
    try {
      $requestArgs = @{
        UseBasicParsing = $true
        Uri = $Uri
        TimeoutSec = $AttemptTimeoutSec
      }
      if ($SkipCertificateCheck) {
        $requestArgs["SkipCertificateCheck"] = $true
      }

      $response = Invoke-WebRequest @requestArgs
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        return $true
      }
      $lastFailure = "HTTP $($response.StatusCode)"
    } catch {
      $lastFailure = $_.Exception.Message
      if ($_.Exception.Response) {
        $lastFailure = "HTTP $([int]$_.Exception.Response.StatusCode): $($_.Exception.Message)"
      }
    }

    Start-Sleep -Seconds 2
  }

  Write-Host "Last HTTP check failure for ${Uri}: $lastFailure" -ForegroundColor Yellow
  return $false
}

function Stop-ExistingPublicTunnels {
  Write-Step "Stopping existing local frpc/reverse-SSH public tunnels"

  Get-Process frpc -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Stopping frpc PID $($_.Id)"
    Stop-Process -Id $_.Id -Force
  }

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

  Start-Sleep -Seconds 1
}

function Ensure-LocalBackend {
  $healthUrl = "http://${LocalBackendHost}:${LocalBackendPort}/health"
  if (Test-HttpOk -Uri $healthUrl -TimeoutSec 5) {
    Write-Host "Local backend is healthy at $healthUrl" -ForegroundColor Green
    return
  }

  if ($SkipBackendStart) {
    throw "Local backend is not reachable at $healthUrl and -SkipBackendStart was set."
  }

  Write-Step "Starting local backend on ${LocalBackendHost}:${LocalBackendPort}"
  if (Test-Path -LiteralPath $backendOut) { Remove-Item -LiteralPath $backendOut -Force }
  if (Test-Path -LiteralPath $backendErr) { Remove-Item -LiteralPath $backendErr -Force }

  $startBackendScript = Join-Path $projectRoot "scripts\dev\start_backend.ps1"
  $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$startBackendScript`" -HostAddress $LocalBackendHost -Port $LocalBackendPort"
  Start-Process -FilePath powershell.exe -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr

  for ($i = 0; $i -lt 60; $i++) {
    if (Test-HttpOk -Uri $healthUrl -TimeoutSec 3) {
      Write-Host "Local backend is healthy at $healthUrl" -ForegroundColor Green
      return
    }
    Start-Sleep -Seconds 2
  }

  Write-Host "--- backend stderr tail ---" -ForegroundColor Yellow
  Get-Content -Tail 120 $backendErr -ErrorAction SilentlyContinue
  throw "Backend did not become healthy at $healthUrl."
}

function Test-RemoteFrps {
  if ($SkipRemoteFrpsCheck) {
    return
  }

  Write-Step "Checking remote frps and Nginx"
  $identityPath = Resolve-Path -LiteralPath (Join-Path $projectRoot $IdentityFile)
  $remote = "$DeployUser@$ServerHost"
  $remoteCommand = "set -e; systemctl is-active frps; sudo ss -lntp | grep -E ':($FrpServerPort|$RemotePort) ' || true; sudo nginx -t >/dev/null"
  ssh -i $identityPath -o StrictHostKeyChecking=accept-new $remote $remoteCommand
}

function Publish-Frontend {
  if ($SkipFrontendPublish) {
    Write-Host "Skipping frontend publish." -ForegroundColor Yellow
    return
  }

  Write-Step "Building and publishing frontend"
  $publishScript = Join-Path $projectRoot "scripts\deploy\publish_frontend_to_ecs.ps1"
  if ($SkipBuild) {
    & $publishScript -ServerHost $ServerHost -DeployUser $DeployUser -IdentityFile $IdentityFile -SkipBuild
  } else {
    & $publishScript -ServerHost $ServerHost -DeployUser $DeployUser -IdentityFile $IdentityFile
  }
}

function Start-FrpcTunnel {
  Write-Step "Starting frpc tunnel"

  if (Test-Path -LiteralPath $frpcOut) { Remove-Item -LiteralPath $frpcOut -Force }
  if (Test-Path -LiteralPath $frpcErr) { Remove-Item -LiteralPath $frpcErr -Force }

  $frpcScript = Join-Path $projectRoot "scripts\deploy\start_public_frp_tunnel.ps1"
  $arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$frpcScript`"",
    "-ServerHost", $ServerHost,
    "-LocalBackendHost", $LocalBackendHost,
    "-LocalBackendPort", $LocalBackendPort,
    "-RemotePort", $RemotePort,
    "-ServerPort", $FrpServerPort
  ) -join " "

  $frpcLauncher = Start-Process -FilePath powershell.exe -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput $frpcOut -RedirectStandardError $frpcErr -PassThru

  for ($i = 0; $i -lt 40; $i++) {
    $outText = ""
    if (Test-Path -LiteralPath $frpcOut) {
      $outText = Get-Content -LiteralPath $frpcOut -Raw -ErrorAction SilentlyContinue
    }
    $errText = ""
    if (Test-Path -LiteralPath $frpcErr) {
      $errText = Get-Content -LiteralPath $frpcErr -Raw -ErrorAction SilentlyContinue
    }

    if ($outText -match "start proxy success") {
      Write-Host "frpc tunnel is connected." -ForegroundColor Green
      return
    }
    if ($outText -match "login to the server failed" -or $errText -match "login to the server failed") {
      Write-Host "--- frpc stdout tail ---" -ForegroundColor Yellow
      Get-Content -Tail 120 $frpcOut -ErrorAction SilentlyContinue
      Write-Host "--- frpc stderr tail ---" -ForegroundColor Yellow
      Get-Content -Tail 120 $frpcErr -ErrorAction SilentlyContinue
      throw "frpc failed to login."
    }
    if ($frpcLauncher.HasExited -and -not (Get-Process frpc -ErrorAction SilentlyContinue)) {
      Start-Sleep -Milliseconds 500
      if (Test-Path -LiteralPath $frpcOut) {
        $outText = Get-Content -LiteralPath $frpcOut -Raw -ErrorAction SilentlyContinue
      }
      if ($outText -match "start proxy success") {
        Write-Host "frpc tunnel is connected." -ForegroundColor Green
        return
      }

      Write-Host "--- frpc stdout tail ---" -ForegroundColor Yellow
      Get-Content -Tail 120 $frpcOut -ErrorAction SilentlyContinue
      Write-Host "--- frpc stderr tail ---" -ForegroundColor Yellow
      Get-Content -Tail 120 $frpcErr -ErrorAction SilentlyContinue
      throw "frpc exited before the tunnel became ready."
    }
    Start-Sleep -Seconds 1
  }

  Write-Host "--- frpc stdout tail ---" -ForegroundColor Yellow
  Get-Content -Tail 120 $frpcOut -ErrorAction SilentlyContinue
  throw "Timed out waiting for frpc tunnel readiness."
}

function Verify-PublicDemo {
  Write-Step "Verifying public demo"
  $healthUrl = "https://$ServerHost/health"
  $rootUrl = "https://$ServerHost/"

  if (-not (Wait-HttpOk -Uri $healthUrl -TimeoutSec 90 -AttemptTimeoutSec 10 -SkipCertificateCheck)) {
    throw "Public health check failed: $healthUrl"
  }
  if (-not (Wait-HttpOk -Uri $rootUrl -TimeoutSec 90 -AttemptTimeoutSec 10 -SkipCertificateCheck)) {
    throw "Public frontend check failed: $rootUrl"
  }

  Write-Host "Public demo is online: $rootUrl" -ForegroundColor Green
}

if (-not $KeepExistingTunnels) {
  Stop-ExistingPublicTunnels
}
Ensure-LocalBackend
Test-RemoteFrps
Publish-Frontend
Start-FrpcTunnel
Verify-PublicDemo

Write-Host ""
Write-Host "Deployment complete. Keep the backend and frpc processes running while the public demo is online." -ForegroundColor Green

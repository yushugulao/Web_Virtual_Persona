param(
  [string]$ServerHost = $env:PERSONA_RAG_PUBLIC_SERVER_HOST,
  [string]$DeployUser = "deploy-admin",
  [string]$EcsIdentityFile = "secrets\public_tunnel\deploy_admin_ed25519",
  [int]$FrpServerPort = 7000,
  [int]$RemotePort = 18001,
  [string]$AutodlHost = "connect.bjb2.seetacloud.com",
  [int]$AutodlPort = 25163,
  [string]$AutodlUser = "root",
  [string]$AutodlIdentityFile = "secrets\autodl_backend\autodl_backend_ed25519",
  [string]$RemoteAppDir = "/opt/web-avatar/backend",
  [string]$Profile = "standard_gpu",
  [switch]$InstallAutodlKeyWithPassword,
  [switch]$SkipFrontendPublish,
  [switch]$SkipBuild,
  [switch]$SkipBackendDeploy,
  [switch]$SkipModelPull,
  [switch]$SkipRemoteFrpsCheck,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ServerHost)) {
  throw "Pass -ServerHost <public-ip-or-domain>, or set PERSONA_RAG_PUBLIC_SERVER_HOST."
}

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$ecsIdentityPath = Resolve-Path -LiteralPath (Join-Path $projectRoot $EcsIdentityFile)

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-HttpOk {
  param(
    [string]$Uri,
    [int]$TimeoutSec = 8,
    [switch]$SkipCertificateCheck
  )
  try {
    $args = @{
      UseBasicParsing = $true
      Uri = $Uri
      TimeoutSec = $TimeoutSec
    }
    if ($SkipCertificateCheck) {
      $args["SkipCertificateCheck"] = $true
    }
    $response = Invoke-WebRequest @args
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
  } catch {
    return $false
  }
}

function Wait-HttpOk {
  param(
    [string]$Uri,
    [int]$TimeoutSec = 120,
    [switch]$SkipCertificateCheck
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $lastFailure = "not attempted"
  while ((Get-Date) -lt $deadline) {
    try {
      $args = @{
        UseBasicParsing = $true
        Uri = $Uri
        TimeoutSec = 10
      }
      if ($SkipCertificateCheck) {
        $args["SkipCertificateCheck"] = $true
      }
      $response = Invoke-WebRequest @args
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        return $true
      }
      $lastFailure = "HTTP $($response.StatusCode)"
    } catch {
      $lastFailure = $_.Exception.Message
    }
    Start-Sleep -Seconds 2
  }
  Write-Host "Last HTTP failure for ${Uri}: $lastFailure" -ForegroundColor Yellow
  return $false
}

function Stop-LocalPublicTunnels {
  Write-Step "Stopping local frpc/reverse-SSH public tunnels"
  $stopScript = Join-Path $projectRoot "scripts\deploy\stop_public_demo.ps1"
  if ($DryRun) {
    Write-Host "DRY RUN: would run $stopScript"
    return
  }
  & $stopScript -RemotePort $RemotePort
}

function Test-RemoteFrps {
  if ($SkipRemoteFrpsCheck) {
    return
  }
  Write-Step "Checking ECS frps and Nginx"
  $remote = "$DeployUser@$ServerHost"
  $remoteCommand = "set -e; systemctl is-active frps; sudo ss -lntp | grep -E ':($FrpServerPort|$RemotePort) ' || true; sudo nginx -t >/dev/null"
  if ($DryRun) {
    Write-Host "DRY RUN ssh ECS: $remoteCommand"
    return
  }
  ssh -i $ecsIdentityPath -o StrictHostKeyChecking=accept-new $remote $remoteCommand
}

function Publish-Frontend {
  if ($SkipFrontendPublish) {
    Write-Host "Skipping frontend publish." -ForegroundColor Yellow
    return
  }
  Write-Step "Publishing frontend to ECS"
  $publishScript = Join-Path $projectRoot "scripts\deploy\publish_frontend_to_ecs.ps1"
  if ($DryRun) {
    Write-Host "DRY RUN: would publish frontend to $ServerHost"
    return
  }
  if ($SkipBuild) {
    & $publishScript -ServerHost $ServerHost -DeployUser $DeployUser -IdentityFile $EcsIdentityFile -SkipBuild
  } else {
    & $publishScript -ServerHost $ServerHost -DeployUser $DeployUser -IdentityFile $EcsIdentityFile
  }
}

function Bootstrap-AutodlKey {
  Write-Step "Checking AutoDL SSH key"
  $bootstrapScript = Join-Path $projectRoot "scripts\deploy\bootstrap_autodl_backend.ps1"
  $scriptArgs = @{
    AutodlHost = $AutodlHost
    AutodlPort = $AutodlPort
    AutodlUser = $AutodlUser
    IdentityFile = $AutodlIdentityFile
  }
  if ($InstallAutodlKeyWithPassword) { $scriptArgs["InstallKeyWithPassword"] = $true }
  if ($DryRun) { $scriptArgs["DryRun"] = $true }
  & $bootstrapScript @scriptArgs
}

function Deploy-AutodlBackend {
  if ($SkipBackendDeploy) {
    Write-Host "Skipping AutoDL backend deploy." -ForegroundColor Yellow
    return
  }
  Write-Step "Deploying backend to AutoDL"
  $script = Join-Path $projectRoot "scripts\deploy\deploy_backend_to_autodl.ps1"
  $scriptArgs = @{
    AutodlHost = $AutodlHost
    AutodlPort = $AutodlPort
    AutodlUser = $AutodlUser
    IdentityFile = $AutodlIdentityFile
    RemoteAppDir = $RemoteAppDir
    Profile = $Profile
    PublicUrl = "https://$ServerHost/"
  }
  if ($SkipModelPull) { $scriptArgs["SkipModelPull"] = $true }
  if ($DryRun) { $scriptArgs["DryRun"] = $true }
  & $script @scriptArgs
}

function Start-AutodlTunnel {
  Write-Step "Starting AutoDL -> ECS frp tunnel"
  $script = Join-Path $projectRoot "scripts\deploy\start_autodl_frp_tunnel.ps1"
  $scriptArgs = @{
    AutodlHost = $AutodlHost
    AutodlPort = $AutodlPort
    AutodlUser = $AutodlUser
    IdentityFile = $AutodlIdentityFile
    ServerHost = $ServerHost
    ServerPort = $FrpServerPort
    RemotePort = $RemotePort
    RemoteAppDir = $RemoteAppDir
  }
  if ($DryRun) { $scriptArgs["DryRun"] = $true }
  & $script @scriptArgs
}

function Verify-EcsLoopback {
  Write-Step "Verifying ECS loopback backend"
  $remote = "$DeployUser@$ServerHost"
  $remoteCommand = "set -e; curl -fsS http://127.0.0.1:$RemotePort/health"
  if ($DryRun) {
    Write-Host "DRY RUN ssh ECS: $remoteCommand"
    return
  }
  ssh -i $ecsIdentityPath -o StrictHostKeyChecking=accept-new $remote $remoteCommand
}

function Verify-PublicDemo {
  Write-Step "Verifying public AutoDL-backed demo"
  if ($DryRun) {
    Write-Host "DRY RUN: would verify https://$ServerHost/health and https://$ServerHost/"
    return
  }
  if (-not (Wait-HttpOk -Uri "https://$ServerHost/health" -TimeoutSec 120 -SkipCertificateCheck)) {
    throw "Public health check failed: https://$ServerHost/health"
  }
  if (-not (Wait-HttpOk -Uri "https://$ServerHost/" -TimeoutSec 120 -SkipCertificateCheck)) {
    throw "Public frontend check failed: https://$ServerHost/"
  }
  if (-not (Wait-HttpOk -Uri "https://$ServerHost/personas" -TimeoutSec 60 -SkipCertificateCheck)) {
    Write-Host "Public /personas did not return 2xx; this may be auth-related, but /health and frontend are online." -ForegroundColor Yellow
  }
  Write-Host "Public AutoDL-backed demo is online: https://$ServerHost/" -ForegroundColor Green
}

Stop-LocalPublicTunnels
Bootstrap-AutodlKey
Test-RemoteFrps
Publish-Frontend
Deploy-AutodlBackend
Start-AutodlTunnel
Verify-EcsLoopback
Verify-PublicDemo

Write-Host ""
Write-Host "Deployment complete. Backend/model runtime is now on AutoDL; ECS remains the public Nginx + frps entry." -ForegroundColor Green

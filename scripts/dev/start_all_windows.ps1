param(
  [string]$HostAddress = "127.0.0.1",
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $ProjectRoot

function Get-PowerShellExecutable {
  $candidates = @()
  if ($PSHOME) {
    $candidates += (Join-Path $PSHOME "powershell.exe")
    $candidates += (Join-Path $PSHOME "pwsh.exe")
  }
  try {
    $currentProcess = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    if ($currentProcess) { $candidates += $currentProcess }
  } catch {
  }
  if ($env:SystemRoot) {
    $candidates += (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe")
    $candidates += (Join-Path $env:SystemRoot "Sysnative\WindowsPowerShell\v1.0\powershell.exe")
    $candidates += (Join-Path $env:SystemRoot "SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
  }
  foreach ($name in @("powershell.exe", "powershell", "pwsh.exe", "pwsh")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
  }
  foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  throw "找不到 PowerShell 可执行文件。请确认 Windows PowerShell 5.1 可用，或修复 PATH 后重试。"
}

$powershell = Get-PowerShellExecutable

Write-Host "Starting backend on http://$HostAddress`:$BackendPort"
$backend = Start-Process -FilePath $powershell `
  -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", "scripts\dev\start_backend.ps1", "-HostAddress", $HostAddress, "-Port", "$BackendPort") `
  -WorkingDirectory $ProjectRoot `
  -PassThru

Write-Host "Starting frontend on http://127.0.0.1:$FrontendPort"
$frontendArgs = "cd '$ProjectRoot\app\frontend'; `$env:VITE_API_BASE_URL='http://$HostAddress`:$BackendPort'; npm run dev -- --host 127.0.0.1 --port $FrontendPort"
$frontend = Start-Process -FilePath $powershell `
  -ArgumentList @("-NoExit", "-Command", $frontendArgs) `
  -WorkingDirectory $ProjectRoot `
  -PassThru

Write-Host "Started processes: backend=$($backend.Id), frontend=$($frontend.Id)"
Write-Host "Close the spawned terminals to stop the services."


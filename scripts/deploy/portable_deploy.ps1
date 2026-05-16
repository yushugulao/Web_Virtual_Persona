param(
  [switch]$DryRun,
  [switch]$DryRunInstall,
  [switch]$CheckOnly,
  [switch]$InstallMissing,
  [switch]$NoInstall,
  [switch]$Yes,
  [switch]$NonInteractive,
  [string]$Answers = "",
  [ValidateSet("auto", "minimal_cpu", "quick_gpu", "standard_gpu", "no_model_dev")]
  [string]$Profile = "auto",
  [ValidateSet("", "local_lan", "direct_public_server", "frp_tunnel", "compute_backend_frp")]
  [string]$Mode = "",
  [switch]$PullModels
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $ProjectRoot

$argsList = @("scripts/deploy/portable_deploy.py", "--profile", $Profile)
if ($Mode) { $argsList += @("--mode", $Mode) }
if ($DryRun) { $argsList += "--dry-run" }
if ($DryRunInstall) { $argsList += "--dry-run-install" }
if ($CheckOnly) { $argsList += "--check-only" }
if ($InstallMissing) { $argsList += "--install-missing" }
if ($NoInstall) { $argsList += "--no-install" }
if ($Yes) { $argsList += "--yes" }
if ($NonInteractive) { $argsList += "--non-interactive" }
if ($Answers) { $argsList += @("--answers", $Answers) }
if ($PullModels) { $argsList += "--pull-models" }

uv run python @argsList

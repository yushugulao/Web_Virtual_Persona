param(
    [string]$Repo = $env:WEB_VIRTUAL_PERSONA_REPO,
    [string]$Branch = $env:WEB_VIRTUAL_PERSONA_BRANCH
)

$ErrorActionPreference = "Stop"

if (-not $Repo) { $Repo = "yushugulao/Web_Virtual_Persona" }
if (-not $Branch) { $Branch = "main" }

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$url = "https://raw.githubusercontent.com/$Repo/$Branch/install.ps1"
$client = New-Object System.Net.WebClient
try {
    $bytes = $client.DownloadData($url)
} finally {
    $client.Dispose()
}

$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
$script = $strictUtf8.GetString($bytes).TrimStart([char]0xFEFF)
$installer = [scriptblock]::Create($script)
$installerArgs = @{
    Repo = $Repo
    Branch = $Branch
}
if ($env:WEB_VIRTUAL_PERSONA_REPLACE -eq "1") { $installerArgs.Replace = $true }
if ($env:WEB_VIRTUAL_PERSONA_DRY_RUN -eq "1") { $installerArgs.DryRun = $true }
if ($env:WEB_VIRTUAL_PERSONA_NO_GUI -eq "1") { $installerArgs.NoGui = $true }
& $installer @installerArgs

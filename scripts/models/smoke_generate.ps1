param(
  [string]$Model = "qwen3:8b",
  [string]$Prompt = "Introduce yourself in one short sentence.",
  [bool]$Think = $true
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
& (Join-Path $PSScriptRoot "set_model_cache_env.ps1") -ProjectRoot $ProjectRoot | Out-Null

& (Join-Path $PSScriptRoot "start_ollama.ps1")

$effectivePrompt = $Prompt
if ($Model.ToLowerInvariant().StartsWith("qwen3") -and -not $Model.ToLowerInvariant().Contains("instruct") -and -not $Think -and -not $Prompt.StartsWith("/no_think")) {
  $effectivePrompt = "/no_think`n`n$Prompt"
}

$body = @{
  model = $Model
  prompt = $effectivePrompt
  stream = $false
  think = $Think
  keep_alive = "30m"
} | ConvertTo-Json -Compress

$result = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:11434/api/generate" `
  -ContentType "application/json; charset=utf-8" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

$cleaned = $result.response
if ($cleaned -match "(?i)</think>") {
  $cleaned = ($cleaned -split "(?i)</think>")[-1].Trim()
}
$cleaned = [regex]::Replace($cleaned, "(?is)<think>.*?</think>", "").Trim()
$result.response = $cleaned
if ($result.PSObject.Properties.Name -contains "thinking") {
  $result.PSObject.Properties.Remove("thinking")
}
if ($result.PSObject.Properties.Name -contains "context") {
  $result.PSObject.Properties.Remove("context")
}
$result | ConvertTo-Json -Depth 6

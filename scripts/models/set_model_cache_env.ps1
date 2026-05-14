param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"

$ModelRoot = Join-Path $ProjectRoot "models"
$OllamaModels = Join-Path $ModelRoot "ollama"
$HuggingFaceRoot = Join-Path $ModelRoot "huggingface"
$HuggingFaceHub = Join-Path $HuggingFaceRoot "hub"
$HuggingFaceDatasets = Join-Path $HuggingFaceRoot "datasets"
$HuggingFaceXet = Join-Path $HuggingFaceRoot "xet"
$SentenceTransformers = Join-Path $HuggingFaceRoot "sentence_transformers"
$TorchHome = Join-Path $ModelRoot "torch"
$ModelScopeCache = Join-Path $ModelRoot "modelscope"

New-Item -ItemType Directory -Force `
  $OllamaModels, `
  $HuggingFaceHub, `
  $HuggingFaceDatasets, `
  $HuggingFaceXet, `
  $SentenceTransformers, `
  $TorchHome, `
  $ModelScopeCache | Out-Null

$env:OLLAMA_MODELS = $OllamaModels
$env:HF_HUB_CACHE = $HuggingFaceHub
$env:HUGGINGFACE_HUB_CACHE = $HuggingFaceHub
$env:TRANSFORMERS_CACHE = $HuggingFaceHub
$env:HF_DATASETS_CACHE = $HuggingFaceDatasets
$env:HF_XET_CACHE = $HuggingFaceXet
$env:SENTENCE_TRANSFORMERS_HOME = $SentenceTransformers
$env:TORCH_HOME = $TorchHome
$env:MODELSCOPE_CACHE = $ModelScopeCache

[PSCustomObject]@{
  ModelRoot = $ModelRoot
  OllamaModels = $OllamaModels
  HuggingFaceHub = $HuggingFaceHub
  HuggingFaceDatasets = $HuggingFaceDatasets
  HuggingFaceXet = $HuggingFaceXet
  SentenceTransformers = $SentenceTransformers
  TorchHome = $TorchHome
  ModelScopeCache = $ModelScopeCache
}

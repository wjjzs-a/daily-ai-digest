# 测试驱动：设置环境变量跑 daily_ai.py，输出统一存 UTF-8
# 用法: powershell -File run_local_test.ps1 [-Model cn:glm-5.3-flash] [-Dry]
param(
    [string]$Base = "http://127.0.0.1:7863/v1",
    [string]$Key = "wb2a-8f4c2d9a6b1e4735a0c8f2e9d7b31c64",
    [string]$Model = "cn:glm-5.3-flash",
    [string]$Fallback = "cn:deepseek-v4.1-flash",
    [switch]$Dry
)

$env:LLM_BASE_URL = $Base
$env:LLM_API_KEY = $Key
$env:LLM_MODEL = $Model
$env:LLM_MODEL_FALLBACK = $Fallback
$env:LLM_MAX_TOKENS = "16000"
if ($Dry) { $env:DRY_RUN = "1" }

$out = Join-Path $PSScriptRoot "last_run.txt"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
& python (Join-Path $PSScriptRoot "daily_ai.py") *> $out
$code = $LASTEXITCODE
Write-Host "exit=$code  output=$out"

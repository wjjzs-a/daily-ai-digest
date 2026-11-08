# run_daily.ps1 - 本地跑一次简报并推送微信
#
# 用途：给 HanaAgent 的定时任务调用，或你手动跑一次。
# 配置在 private/local_config.json（不入库）+ private/wkbd_cred.json（凭证）。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File "D:\小美\_work\daily_ai\run_daily.ps1"

$ErrorActionPreference = 'Stop'
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Dir

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

# 凭证从文件读进环境变量，脚本自己会顺便读 local_config.json
$credPath = Join-Path $Dir 'private\wkbd_cred.json'
if (Test-Path $credPath) {
    $env:WKBD_CRED = [IO.File]::ReadAllText($credPath, [Text.Encoding]::UTF8).TrimStart([char]0xFEFF)
} else {
    Write-Output "[run_daily] 缺 $credPath，模型调用会失败"
}

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { Write-Output "[run_daily] 找不到 python"; exit 1 }

& $py (Join-Path $Dir 'daily_ai.py')
$code = $LASTEXITCODE
Write-Output "[run_daily] 退出码 $code"
exit $code

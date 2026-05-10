# run_fetch_details.ps1
# タスクスケジューラから30分ごとに実行される
# 売切れ商品の検知 → eBay出品自動取り消し

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$toolDir    = Split-Path -Parent $scriptDir
$logDir     = Join-Path $toolDir "logs"
$logFile    = Join-Path $logDir "fetch_details_$(Get-Date -Format 'yyyyMMdd').log"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# 7日より古いログを削除
Get-ChildItem $logDir -Filter "fetch_details_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force

Set-Location $toolDir

$ts = Get-Date -Format "HH:mm:ss"
"[$ts] === fetch-details 開始 ===" | Add-Content $logFile

python -m src.main fetch-details 2>&1 | Add-Content $logFile

$ts = Get-Date -Format "HH:mm:ss"
"[$ts] === fetch-details 完了 ===" | Add-Content $logFile

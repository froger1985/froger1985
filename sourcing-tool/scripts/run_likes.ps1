# run_likes.ps1
# タスクスケジューラから朝・夜に実行される
# メルカリいいね取得 → DB保存 → いいね解除検知

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$toolDir    = Split-Path -Parent $scriptDir
$logDir     = Join-Path $toolDir "logs"
$logFile    = Join-Path $logDir "likes_$(Get-Date -Format 'yyyyMMdd').log"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# 7日より古いログを削除
Get-ChildItem $logDir -Filter "likes_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force

Set-Location $toolDir

$ts = Get-Date -Format "HH:mm:ss"
"[$ts] === likes --save 開始 ===" | Add-Content $logFile

python -m src.main likes --save 2>&1 | Add-Content $logFile

$ts = Get-Date -Format "HH:mm:ss"
"[$ts] === likes --save 完了 ===" | Add-Content $logFile

# run_likes.ps1
# Runs morning and evening via Task Scheduler
# Fetches Mercari likes, saves to DB, detects unliked items

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$toolDir    = Split-Path -Parent $scriptDir
$logDir     = Join-Path $toolDir "logs"
$logFile    = Join-Path $logDir "likes_$(Get-Date -Format 'yyyyMMdd').log"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# Delete logs older than 7 days
Get-ChildItem $logDir -Filter "likes_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force

Set-Location $toolDir

$ts = Get-Date -Format "HH:mm:ss"
"[$ts] === likes --save START ===" | Add-Content $logFile

python -m src.main likes --save 2>&1 | Add-Content $logFile

$ts = Get-Date -Format "HH:mm:ss"
"[$ts] === likes --save END ===" | Add-Content $logFile

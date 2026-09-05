# run_fetch_details.ps1
# Runs every 10 min via Task Scheduler
# Detects sold-out items and auto-delists from eBay

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$toolDir    = Split-Path -Parent $scriptDir
$logDir     = Join-Path $toolDir "logs"
$logFile    = Join-Path $logDir "fetch_details_$(Get-Date -Format 'yyyyMMdd').log"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# Delete logs older than 7 days
Get-ChildItem $logDir -Filter "fetch_details_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force

Set-Location $toolDir

$ts = Get-Date -Format "HH:mm:ss"
"[$ts] === fetch-details START ===" | Add-Content $logFile

python -m src.main fetch-details 2>&1 | Add-Content $logFile

$ts = Get-Date -Format "HH:mm:ss"
"[$ts] === fetch-details END ===" | Add-Content $logFile

# setup_scheduler.ps1
# Run this script as Administrator

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$toolDir   = Split-Path -Parent $scriptDir

$ps = "powershell.exe"
$hidden = "-NonInteractive -WindowStyle Hidden"

# =====================================================
# 1. fetch-details - every 10 minutes
# =====================================================
$action   = New-ScheduledTaskAction -Execute $ps `
              -Argument "$hidden -File `"$scriptDir\run_fetch_details.ps1`""
$trigger  = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 10) `
              -Once -At (Get-Date).Date
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 9) `
              -StartWhenAvailable
Register-ScheduledTask `
    -TaskName    "SourcingTool-FetchDetails" `
    -Description "Sold-out detection and eBay delisting - every 10 min" `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force | Out-Null
Write-Host "[OK] SourcingTool-FetchDetails  (every 10 min)"

# =====================================================
# 2. Mercari likes - 07:00 AM and 22:00 PM daily
# =====================================================
$action    = New-ScheduledTaskAction -Execute $ps `
               -Argument "-File `"$scriptDir\run_likes.ps1`""
$triggerAM = New-ScheduledTaskTrigger -Daily -At "07:00"
$triggerPM = New-ScheduledTaskTrigger -Daily -At "22:00"
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
               -StartWhenAvailable

Register-ScheduledTask `
    -TaskName    "SourcingTool-Likes-AM" `
    -Description "Mercari likes fetch - 07:00 AM" `
    -Action      $action `
    -Trigger     $triggerAM `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force | Out-Null
Write-Host "[OK] SourcingTool-Likes-AM  (daily 07:00)"

Register-ScheduledTask `
    -TaskName    "SourcingTool-Likes-PM" `
    -Description "Mercari likes fetch - 22:00 PM" `
    -Action      $action `
    -Trigger     $triggerPM `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force | Out-Null
Write-Host "[OK] SourcingTool-Likes-PM  (daily 22:00)"

Write-Host ""
Write-Host "All tasks registered. Check Task Scheduler to verify."
Write-Host "Manual test: Start-ScheduledTask -TaskName 'SourcingTool-FetchDetails'"

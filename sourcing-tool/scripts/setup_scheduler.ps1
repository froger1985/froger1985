# setup_scheduler.ps1
# タスクスケジューラへの登録スクリプト
# PowerShell を「管理者として実行」してから実行してください

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$toolDir   = Split-Path -Parent $scriptDir

# --- 共通設定 ---
$ps = "powershell.exe"
$hidden = "-NonInteractive -WindowStyle Hidden"

# =====================================================
# 1. Web UI 自動起動（PC起動時）
# =====================================================
$action   = New-ScheduledTaskAction -Execute $ps `
              -Argument "$hidden -File `"$scriptDir\start_ui.ps1`""
$trigger  = New-ScheduledTaskTrigger -AtLogon
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 24) `
              -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask `
    -TaskName    "SourcingTool-UI" `
    -Description "Sourcing Tool Web UI をログオン時に起動" `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force | Out-Null
Write-Host "[OK] SourcingTool-UI  (ログオン時に起動)"

# =====================================================
# 2. 売切れ検知 fetch-details（30分ごと）
# =====================================================
$action   = New-ScheduledTaskAction -Execute $ps `
              -Argument "$hidden -File `"$scriptDir\run_fetch_details.ps1`""
$trigger  = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) `
              -Once -At (Get-Date).Date   # 今日の 00:00 を起点に繰り返す
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 25) `
              -StartWhenAvailable
Register-ScheduledTask `
    -TaskName    "SourcingTool-FetchDetails" `
    -Description "売切れ検知・eBay出品取り消し（30分ごと）" `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force | Out-Null
Write-Host "[OK] SourcingTool-FetchDetails  (30分ごと)"

# =====================================================
# 3. いいね取得（朝 7:00 / 夜 22:00）
# =====================================================
$action    = New-ScheduledTaskAction -Execute $ps `
               -Argument "-File `"$scriptDir\run_likes.ps1`""  # headed browser なので WindowStyle Hidden は外す
$triggerAM = New-ScheduledTaskTrigger -Daily -At "07:00"
$triggerPM = New-ScheduledTaskTrigger -Daily -At "22:00"
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
               -StartWhenAvailable

Register-ScheduledTask `
    -TaskName    "SourcingTool-Likes-AM" `
    -Description "メルカリいいね取得（朝 7:00）" `
    -Action      $action `
    -Trigger     $triggerAM `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force | Out-Null
Write-Host "[OK] SourcingTool-Likes-AM  (毎日 07:00)"

Register-ScheduledTask `
    -TaskName    "SourcingTool-Likes-PM" `
    -Description "メルカリいいね取得（夜 22:00）" `
    -Action      $action `
    -Trigger     $triggerPM `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force | Out-Null
Write-Host "[OK] SourcingTool-Likes-PM  (毎日 22:00)"

Write-Host ""
Write-Host "登録完了。タスクスケジューラで確認できます。"
Write-Host "手動テスト: Start-ScheduledTask -TaskName 'SourcingTool-FetchDetails'"

# start_ui.ps1
# PC起動時にタスクスケジューラから実行し、Web UIをバックグラウンドで起動する

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$toolDir   = Split-Path -Parent $scriptDir

Set-Location $toolDir
python -m src.main ui

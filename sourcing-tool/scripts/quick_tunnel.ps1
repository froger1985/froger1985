# quick_tunnel.ps1
# ドメインなしで今すぐスマホからアクセスしたい場合の一時トンネル
# 実行するたびに異なるURLが発行される（セッション中のみ有効）
# Web UI が起動済みの状態で実行してください

Write-Host "一時トンネルを起動中..."
Write-Host "表示された trycloudflare.com の URL をスマホで開いてください"
Write-Host "終了するには Ctrl+C"
Write-Host ""
cloudflared tunnel --url http://localhost:8000

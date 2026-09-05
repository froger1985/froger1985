# setup_cloudflare_tunnel.ps1
# Cloudflare Tunnel をインストール・設定してスマホから Web UI にアクセスできるようにする
# 初回のみ実行（以降は自動起動）

# =====================================================
# Step 1: cloudflared のインストール
# =====================================================
Write-Host "=== Step 1: cloudflared インストール ==="
$installed = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($installed) {
    Write-Host "[OK] cloudflared はすでにインストール済みです"
} else {
    Write-Host "インストール中..."
    winget install Cloudflare.cloudflared
    Write-Host "[OK] インストール完了。ターミナルを再起動して再度このスクリプトを実行してください"
    exit
}

# =====================================================
# Step 2: Cloudflare アカウントにログイン
# =====================================================
Write-Host ""
Write-Host "=== Step 2: Cloudflare ログイン ==="
Write-Host "ブラウザが開きます。Cloudflareアカウントでログインしてください。"
Write-Host "アカウントがなければ https://dash.cloudflare.com/sign-up で無料登録できます"
Write-Host ""
Read-Host "準備ができたら Enter を押してください"
cloudflared tunnel login

# =====================================================
# Step 3: トンネルの作成
# =====================================================
Write-Host ""
Write-Host "=== Step 3: トンネル作成 ==="
cloudflared tunnel create sourcing-tool

# =====================================================
# Step 4: 設定ファイルの作成
# =====================================================
Write-Host ""
Write-Host "=== Step 4: 設定ファイル作成 ==="

$configDir  = "$env:USERPROFILE\.cloudflared"
$configFile = "$configDir\config.yml"

# トンネルIDを取得
$tunnelInfo = cloudflared tunnel list --output json | ConvertFrom-Json
$tunnel     = $tunnelInfo | Where-Object { $_.name -eq "sourcing-tool" } | Select-Object -First 1
if (-not $tunnel) {
    Write-Host "[ERROR] トンネルが見つかりません。手動で確認してください: cloudflared tunnel list"
    exit 1
}

$tunnelId = $tunnel.id
Write-Host "トンネルID: $tunnelId"

# ドメイン設定
Write-Host ""
Write-Host "Cloudflareで管理しているドメインを入力してください"
Write-Host "例: myapp.example.com"
Write-Host "（ドメインがない場合は Ctrl+C で中断し、下記のクイックトンネルを使用してください）"
$hostname = Read-Host "ホスト名"

@"
tunnel: $tunnelId
credentials-file: $configDir\$tunnelId.json

ingress:
  - hostname: $hostname
    service: http://localhost:8000
  - service: http_status:404
"@ | Set-Content $configFile -Encoding UTF8

Write-Host "[OK] 設定ファイル作成: $configFile"

# =====================================================
# Step 5: DNS レコードの設定
# =====================================================
Write-Host ""
Write-Host "=== Step 5: DNS 設定 ==="
cloudflared tunnel route dns sourcing-tool $hostname

# =====================================================
# Step 6: Windows サービスとして登録（自動起動）
# =====================================================
Write-Host ""
Write-Host "=== Step 6: Windowsサービス登録 ==="
cloudflared service install

Write-Host ""
Write-Host "=========================================="
Write-Host "設定完了！"
Write-Host "スマホから https://$hostname でアクセスできます"
Write-Host "サービスはPC起動時に自動で立ち上がります"
Write-Host "=========================================="

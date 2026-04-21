# 子供用DIY GPSトラッカー

子供の安全を見守るためのGPSトラッカーを自作するガイドです。
ESP32 + NEO-6M GPS + SIM800L の組み合わせで、Google Apps Script をバックエンドに使用します。

## システム構成

```
[ESP32 + GPS + SIM] ──HTTPS──> [Google Apps Script] ──書き込み──> [Google Sheets]
                                        |
                               [ブラウザで地図表示]
```

## 必要なハードウェア

| 部品 | 型番 | 参考価格 |
|------|------|----------|
| マイコン | ESP32-DevKitC | ¥600〜 |
| GPS モジュール | NEO-6M | ¥800〜 |
| GSM モジュール | SIM800L | ¥1,200〜 |
| バッテリー | 3.7V Li-Po 1000mAh | ¥500〜 |
| 充電モジュール | TP4056 | ¥100〜 |
| SIM カード | SORACOM Air または IIJmio | ¥500〜/月 |

**合計目安: ¥4,000〜6,000（初期費用）+ 通信費**

> SIM800L は 2G のみ対応です。4G が必要な場合は SIM7600 シリーズを推奨します（¥3,000〜）。

## 配線図

```
NEO-6M GPS          ESP32
  VCC  ──────────── 3.3V
  GND  ──────────── GND
  TX   ──────────── GPIO16 (RX1)
  RX   ──────────── GPIO17 (TX1)

SIM800L             ESP32
  VCC  ──────────── 3.7V (バッテリー直結 ※ ESP32の5Vピンは不可)
  GND  ──────────── GND
  TXD  ──────────── GPIO26 (RX)
  RXD  ──────────── GPIO27 (TX)

バッテリー → TP4056充電モジュール → ESP32(5V) & SIM800L(3.7V直結)
```

## セットアップ手順

### 1. Google Apps Script の準備

1. [script.google.com](https://script.google.com) を開き「新しいプロジェクト」を作成
2. `server/Code.gs` の内容を貼り付ける
3. 「ファイル → 新規 → HTML」で `map` という名前のHTMLファイルを作成し `server/map.html` の内容を貼り付ける
4. 「デプロイ → 新しいデプロイ → ウェブアプリ」を選択
5. 「アクセスできるユーザー」を **全員** に設定してデプロイ
6. 表示されるURLをコピーしてメモする
   - 例: `https://script.google.com/macros/s/AKfy.../exec`

### 2. Google Maps API キーの取得

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. **Maps JavaScript API** を有効化
3. APIキーを発行し、`server/map.html` の `YOUR_GOOGLE_MAPS_API_KEY` を置換
4. GASプロジェクトに戻り「デプロイを管理 → 編集 → 新バージョン」で再デプロイ

### 3. Arduino IDE のセットアップ

1. [Arduino IDE](https://www.arduino.cc/en/software) をインストール
2. 「ファイル → 環境設定 → 追加のボードマネージャのURL」に以下を追加:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. 「ツール → ボード → ボードマネージャ」で `esp32` を検索してインストール
4. ライブラリマネージャから以下をインストール:
   - `TinyGPS++` by Mikal Hart
   - `TinyGSM` by Volodymyr Shymanskyy
   - `ArduinoHttpClient` by Arduino

### 4. ファームウェアの書き込み

1. `device/firmware.ino` を Arduino IDE で開く
2. 以下の定数を書き換える:
   - `GAS_PATH`: 手順1でコピーしたURLのパス部分 (`/macros/s/.../exec`)
   - `DEVICE_ID`: 識別名（例: `"child01"`）
   - APN設定: 使用するSIMカードに合わせる（下表参照）
3. 「ツール → ボード → ESP32 Dev Module」を選択
4. USBで接続して書き込む

### 5. 動作確認

1. シリアルモニタ（115200bps）を開く
2. `GPRS接続成功` が表示されることを確認
3. 屋外に出て GPS が測位されると `送信中` のログが出る
4. GASのURLをブラウザで開くと地図にピンが表示される

## SIM カードのAPN設定

| キャリア | APN | ユーザー名 | パスワード |
|---------|-----|-----------|----------|
| SORACOM Air | `soracom.io` | `sora` | `sora` |
| IIJmio | `iijmio.jp` | `mio@iij` | `iij` |
| OCN モバイル | `lte-d.ocn.ne.jp` | `mobileid@ocn` | `mobile` |
| mineo (au) | `mineo-d.jp` | `mineo@k-opti.com` | `mineo` |

## バッテリー駆動時間の目安

| 送信間隔 | 1000mAh 時の目安 |
|---------|------------------|
| 30秒 | 約4〜6時間 |
| 60秒 | 約6〜10時間 |
| 5分 | 約12〜20時間 |

## 注意事項

- **プライバシー**: 子供本人に装置の存在を伝えることを推奨します
- **電波法**: 日本国内で使用可能な認証済みモジュールを使用してください
- **SIM800L の電源**: SIM800L は瞬間的に2Aの電流を消費します。ESP32の3.3Vピンから給電すると不安定になるため、バッテリーから直接給電してください
- **屋内**: 建物内ではGPS精度が低下します。Wi-Fiの場合はEPS32の内蔵Wi-Fiで代替も可能です

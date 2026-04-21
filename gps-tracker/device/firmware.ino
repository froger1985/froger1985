// 子供用GPSトラッカー ファームウェア
// 対応ハードウェア: ESP32 + NEO-6M GPS + SIM800L
// 必要ライブラリ: TinyGPS++, TinyGSM, ArduinoHttpClient

#define TINY_GSM_MODEM_SIM800

#include <TinyGsmClient.h>
#include <TinyGPS++.h>
#include <HardwareSerial.h>
#include <ArduinoHttpClient.h>

// ピン設定
#define GPS_RX_PIN 16
#define GPS_TX_PIN 17
#define SIM_RX_PIN 26
#define SIM_TX_PIN 27

// SIM / APN 設定 (SORACOM Air の場合)
const char APN[]  = "soracom.io";
const char USER[] = "sora";
const char PASS[] = "sora";

// Google Apps Script サーバー設定
// GASデプロイURLの /macros/s/.../exec 部分を設定
const char GAS_HOST[] = "script.google.com";
const int  GAS_PORT   = 443;
const char GAS_PATH[] = "/macros/s/YOUR_DEPLOYMENT_ID/exec";

// このデバイスの識別名
const char DEVICE_ID[] = "child01";

// GPS送信間隔 (ミリ秒)
const unsigned long SEND_INTERVAL = 60000UL; // 60秒

HardwareSerial      gpsSerial(1);
HardwareSerial      simSerial(2);
TinyGsm             modem(simSerial);
TinyGsmClientSecure gsmClient(modem);
HttpClient          http(gsmClient, GAS_HOST, GAS_PORT);
TinyGPSPlus         gps;

unsigned long lastSendMs = 0;

void setup() {
  Serial.begin(115200);
  Serial.println("\n=== GPS トラッカー起動 ===");

  gpsSerial.begin(9600, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
  simSerial.begin(9600, SERIAL_8N1, SIM_RX_PIN, SIM_TX_PIN);

  delay(3000);
  Serial.println("モデム初期化中...");
  modem.restart();

  Serial.print("APN接続中: ");
  Serial.println(APN);
  if (!modem.gprsConnect(APN, USER, PASS)) {
    Serial.println("GPRS接続失敗 - 30秒後に再起動");
    delay(30000);
    ESP.restart();
  }
  Serial.println("GPRS接続成功");
}

void loop() {
  // GPSデータを継続的に読み込む
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
  }

  if (millis() - lastSendMs >= SEND_INTERVAL) {
    lastSendMs = millis();

    if (gps.location.isValid() && gps.location.age() < 5000) {
      sendLocation();
    } else {
      Serial.print("GPS未測位 (衛星数: ");
      Serial.print(gps.satellites.value());
      Serial.println(") - スキップ");
    }

    // GPRS接続が切れていたら再接続
    if (!modem.isGprsConnected()) {
      Serial.println("GPRS再接続中...");
      modem.gprsConnect(APN, USER, PASS);
    }
  }
}

void sendLocation() {
  double lat  = gps.location.lat();
  double lng  = gps.location.lng();
  int    sats = (int)gps.satellites.value();

  String path = String(GAS_PATH)
    + "?device=" + DEVICE_ID
    + "&lat="    + String(lat, 6)
    + "&lng="    + String(lng, 6)
    + "&sats="   + String(sats);

  Serial.print("送信中: lat=");
  Serial.print(lat, 6);
  Serial.print(" lng=");
  Serial.println(lng, 6);

  http.beginRequest();
  http.get(path);
  http.sendHeader("User-Agent", "ESP32-GPS-Tracker/1.0");
  http.endRequest();

  int statusCode = http.responseStatusCode();
  http.stop();

  Serial.print("HTTP応答: ");
  Serial.println(statusCode);
}

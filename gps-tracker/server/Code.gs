// GPS トラッカー - Google Apps Script サーバー
// スプレッドシートにGPSデータを記録し、地図を配信します

var SHEET_NAME = 'locations';

function doGet(e) {
  var params = e.parameter || {};

  // デバイスからのGPSデータ受信
  if (params.lat && params.lng) {
    return recordLocation(params);
  }

  // 最新位置情報をJSON返却 (?action=latest)
  if (params.action === 'latest') {
    return getLatestLocations(params.device || null);
  }

  // デフォルト: 地図HTMLを返す
  return HtmlService.createHtmlOutputFromFile('map')
    .setTitle('子供の位置情報')
    .setSandboxMode(HtmlService.SandboxMode.IFRAME);
}

function recordLocation(params) {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME) || createSheet(ss);

  sheet.appendRow([
    new Date().toISOString(),
    params.device  || 'unknown',
    parseFloat(params.lat),
    parseFloat(params.lng),
    parseInt(params.sats    || '0'),
    parseInt(params.battery || '-1')
  ]);

  return ContentService
    .createTextOutput(JSON.stringify({ status: 'ok' }))
    .setMimeType(ContentService.MimeType.JSON);
}

function createSheet(ss) {
  var sheet = ss.insertSheet(SHEET_NAME);
  sheet.appendRow(['timestamp', 'device', 'lat', 'lng', 'satellites', 'battery']);
  sheet.setFrozenRows(1);
  return sheet;
}

// map.html から google.script.run.getLocationsForMap() で呼び出す
function getLocationsForMap() {
  return getLatestLocationsData(null);
}

function getLatestLocations(deviceId) {
  var data = getLatestLocationsData(deviceId);
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function getLatestLocationsData(deviceId) {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) return { locations: [] };

  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return { locations: [] };

  var headers = values[0];
  var latest  = {};

  values.slice(1).forEach(function(row) {
    var rec = {};
    headers.forEach(function(h, i) { rec[h] = row[i]; });
    var dev = rec.device;
    if (deviceId && dev !== deviceId) return;
    if (!latest[dev] || rec.timestamp > latest[dev].timestamp) {
      latest[dev] = rec;
    }
  });

  return { locations: Object.values(latest) };
}

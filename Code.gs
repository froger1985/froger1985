/**
 * メール本文テンプレートに変数を差し込み、Gmail の下書きを作成します。
 * @param {string} subject - メール件名
 * @param {string} bodyTemplate - 本文テンプレート。{{name}} のようなプレースホルダに対応
 * @param {Object} variables - プレースホルダへ差し込むキーと値のセット
 * @returns {GoogleAppsScript.Gmail.GmailDraft} 作成した下書き
 */
function createMailDraft(subject, bodyTemplate, variables) {
  var body = mergeTemplate(bodyTemplate, variables || {});
  return GmailApp.createDraft(subject, '', { htmlBody: body });
}

/**
 * Web アプリからの GET リクエストを処理します。
 * @param {GoogleAppsScript.Events.DoGet} e
 * @returns {GoogleAppsScript.Content.TextOutput}
 */
function doGet(e) {
  return handleRequest(e || {}, 'GET');
}

/**
 * Web アプリからの POST リクエストを処理します。
 * @param {GoogleAppsScript.Events.DoPost} e
 * @returns {GoogleAppsScript.Content.TextOutput}
 */
function doPost(e) {
  return handleRequest(e || {}, 'POST');
}

/**
 * GET/POST をまとめて処理し、下書きを作成します。
 * 以下のパラメータを受け付けます。
 * - subject: メール件名
 * - template: 本文テンプレート（{{key}} プレースホルダに対応）
 * - variables: JSON 文字列で渡す任意の変数マップ
 * - spreadsheetId, sheetName, rowIndex: シートの指定行から値を差し込み
 * - その他のクエリパラメータも変数として差し込み
 *
 * @param {Object} e - doGet/doPost から渡されるオブジェクト
 * @param {string} method - 呼び出しメソッド名（GET/POST）
 * @returns {GoogleAppsScript.Content.TextOutput}
 */
function handleRequest(e, method) {
  var params = e.parameter || {};
  var template = params.template || 'Hello {{name}}, this is a sample template.';
  var subject = params.subject || 'Draft from Web App (' + method + ')';
  var variables = buildVariables(params);

  if (params.spreadsheetId && params.sheetName) {
    var rowIndex = Number(params.rowIndex || 1);
    var sheetData = getSheetData(params.spreadsheetId, params.sheetName);
    if (sheetData[rowIndex - 1]) {
      variables = Object.assign({}, sheetData[rowIndex - 1], variables);
    }
  }

  var draft = createMailDraft(subject, template, variables);

  var payload = {
    status: 'created',
    method: method,
    subject: draft.getMessage().getSubject(),
    bodyPreview: draft.getMessage().getPlainBody().slice(0, 120),
    variablesUsed: variables
  };

  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * テンプレート文字列内の {{key}} に変数を差し込みます。
 * @param {string} template
 * @param {Object} variables
 * @returns {string}
 */
function mergeTemplate(template, variables) {
  return template.replace(/\{\{(.*?)\}\}/g, function(match, key) {
    var trimmedKey = key.trim();
    return Object.prototype.hasOwnProperty.call(variables, trimmedKey)
      ? variables[trimmedKey]
      : '';
  });
}

/**
 * リクエストパラメータから差し込み用の変数を組み立てます。
 * @param {Object} params
 * @returns {Object}
 */
function buildVariables(params) {
  var directVariables = {};
  Object.keys(params).forEach(function(key) {
    if (['subject', 'template', 'variables', 'spreadsheetId', 'sheetName', 'rowIndex'].indexOf(key) === -1) {
      directVariables[key] = params[key];
    }
  });

  if (!params.variables) {
    return directVariables;
  }

  try {
    var parsed = JSON.parse(params.variables);
    if (parsed && typeof parsed === 'object') {
      return Object.assign({}, parsed, directVariables);
    }
  } catch (error) {
    Logger.log('Failed to parse variables JSON: ' + error);
  }

  return directVariables;
}

/**
 * スプレッドシートからヘッダー付きデータを取得し、オブジェクトの配列として返します。
 * @param {string} spreadsheetId
 * @param {string} sheetName
 * @returns {Object[]}
 */
function getSheetData(spreadsheetId, sheetName) {
  var sheet = SpreadsheetApp.openById(spreadsheetId).getSheetByName(sheetName);
  if (!sheet) {
    throw new Error('Sheet "' + sheetName + '" not found');
  }

  var values = sheet.getDataRange().getValues();
  if (values.length < 2) {
    return [];
  }

  var headers = values[0];
  return values.slice(1).map(function(row) {
    var record = {};
    headers.forEach(function(header, index) {
      record[header] = row[index];
    });
    return record;
  });
}

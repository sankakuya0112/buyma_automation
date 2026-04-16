/**********************************
*   スクレイピングスクリプト
*   XXXX IPC CONNECTION XXXX
*
* 初期化
* init-scraper -> InitScraper(event)
*
* ディレクトリ選択
* open-file-scraper -> OpenFileScraper(event)
*
* SQLログイン
* sql-login -> SqlLogin(event, email, password, value)
*
* スクレイピング開始
* start-scrapy -> StartScrapy(event, args_list)
**********************************/

// requires
const {ipcMain, dialog} = require("electron");
const fs = require("fs");

//requires components
const common = require("./common.js");


function IPCInitialize () {
  ipcMain.on("init-scraper", (event) => {
    InitScraper(event)
  });

  ipcMain.on("open-file-scraper", (event) => {
    OpenFileScraper(event)
  });

  ipcMain.on("sql-login", (event, email, password, value) => {
    SqlLogin(event, email, password, value)
  });

  ipcMain.on("start-scrapy", (event, args_list) => {
    StartScrapy(event, args_list)
  });
}

function InitScraper (event) {
  try {
    fs.statSync(dir_data);
    console.log("デフォルトフォルダが存在したので開きます。");
    event.sender.send("selected-directory", dir_data);
  } catch (error) {
    console.log(error);
  }
  // パラメータが存在すれば読み込む
  common.LoadConf(event, "scraper");
}

function OpenFileScraper (event) {
  dialog
    .showOpenDialog({
      properties: ["openDirectory"],
    })
    .then((folder) => {
      if (folder.filePaths[0]) {
        // 選択したディレクトリを表示
        event.sender.send("selected-directory", folder.filePaths[0]);
      }
    });
}

function SqlLogin (event, email, password, value) {
  console.log(email, password);
  args_list = {
    email: email,
    password: password,
    value: value,
  };

  // pyarmorを使用した場合distディレクトリにexhibition.pyが存在するのでoptionsで指定
  let pyshell = common.PyShell("login.py", args_list);

  pyshell.on("message", function (message) {
    message = common.toString(message);
    console.log(message)
    // ログイン情報を保存
    if (message == "False") {
      event.sender.send("log-create", "認証に失敗しました");
    } else if (message === "one time login key ***scraper***") {
      scraper_key = message;
    } else if (message.indexOf(">>>>>") !== -1) {
      event.sender.send("log-create", message);
    } else {
      // datetime&シングルクオテーションがあるとエラーになる
      message = message.replace(/'/g, '"');
      event.sender.send("load-login-data", message);
    }
  });

  pyshell.on("stderr", function (message) {
    common.ErrorLog(event, message);
  });

  pyshell.end(function (err, code, signal) {
    if (err) throw err;
    event.sender.send("log-create", "認証が終了しました");
  });
}

function StartScrapy (event, args_list) {
  // 認証チェック
  if (scraper_key !== "one time login key ***scraper***") {
    event.sender.send("log-create", "認証が完了していません。");
    return;
  }
  // confを更新する
  args_list = JSON.parse(args_list);
  common.WriteConf(event, args_list, "scraper");

  // pyarmorを使用した場合distディレクトリにexhibition.pyが存在するのでoptionsで指定
  let pyshell = common.PyShell("scrapy_start.py", args_list);

  pyshell.on("message", function (message) {
    message = common.toString(message);
    event.sender.send("log-create", message);
  });

  pyshell.on("stderr", function (message) {
    common.ErrorLog(event, message);
  });

  pyshell.end(function (err, code, signal) {
    if (err) throw err;
    // 処理が終了した時に、設定情報を再度反映させる
    common.LoadConf(event, "scraper");
    event.sender.send("log-create", "処理は全て終了しました");
  });
}

module.exports = {IPCInitialize}
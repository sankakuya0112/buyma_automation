/**********************************
*   マネージャースクリプト
*   XXXX IPC CONNECTION XXXX
*
* 初期化
* init-manager -> InitManager(event)
*
* ディレクトリ選択
* open-file-manager -> OpenFileManager(event)
*
* マネージャー開始
* start-manager -> StartManager(event, args_list)
**********************************/

// constants
const {ipcMain, dialog} = require("electron");
const fs = require("fs");
const path = require("path");
const src_dir = path.dirname(__dirname)

// common components
const common = require('./common.js')

function IPCInitialize() {
  ipcMain.on("init-manager", (event) => {
    InitManager(event);
  })

  ipcMain.on("open-file-manager", (event) => {
    OpenFileManager(event);
  })

  ipcMain.on("start-manager", (event, args_list) => {
    StartManager(event, args_list);
  })
}

function InitManager(event) {
  try {
    fs.statSync(dir_account);
    console.log("デフォルトフォルダが存在したので開きます。");
    event.sender.send("selected-directory", dir_account);
  } catch (error) {
    console.log(error);
  }
  common.LoadConf(event, "manager");
}

function OpenFileManager(event) {
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

function StartManager(event, args_list) {
  args_list = JSON.parse(args_list);
  args_list["electron_dir"] = src_dir;

  // confを更新する
  common.WriteConf(event, args_list, "manager");

  // pyarmorを使用した場合distディレクトリにexhibition.pyが存在するのでoptionsで指定
  let pyshell = common.PyShell("BuyManager.py", args_list);

  pyshell.on("message", function (message) {
    message = common.toString(message);
    // received a message sent from the Python script (a simple "print" statement)
    event.sender.send("log-create", message);
  });

  pyshell.end(function (err, code, signal) {
    if (err) throw err;
    event.sender.send("log-create", "処理は全て終了しました");
  });
}

module.exports = {IPCInitialize}
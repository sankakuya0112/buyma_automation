/**********************************
*   BASEスクリプト
*   XXXX IPC CONNECTION XXXX
*
* 説明
* init-base
*
* 説明
* start-base -> StartBase(event, args_list)
**********************************/

// requires
const {ipcMain} = require("electron");
const fs = require("fs");
const path = require("path");

//requires components
const common = require("./common.js");

function IPCInitialize() {
  ipcMain.on("init-base", (event) => {
    // パラメータが存在すれば読み込む
    common.LoadConf(event, "base");
    // dataフォルダが存在すれば配下のディレクトリを表示させる
    base_dir_select(event);
  });
  ipcMain.on("start-base", (event, args_list) => {
    StartBase(event, args_list)
  })
}

function base_dir_select(event) {
  try {
    fs.statSync(dir_data);
    console.log(dir_data + "の中のフォルダを開きます。");
    event.sender.send("selected-directory", dir_data);
    // ディレクトリ&ファイル選択ボタン
    fs.readdir(dir_data, function (err, list) {
      if (err) {
        console.log(err);
      } else {
        var dirfile_list = [];
        console.log(list);
        for (var i = 0; i < list.length; i++) {
          var dir_check = fs
            .statSync(path.join(dir_data, list[i]))
            .isDirectory();
          if (dir_check || list[i].indexOf(".csv") !== -1) {
            dirfile_list.push(list[i]);
          }
        }
        event.sender.send("make-dirfile-button", dirfile_list);
      }
    });
  } catch (error) {
    console.log(error);
  }
}

function StartBase(event, args_list) {
  // confを更新する
  args_list = JSON.parse(args_list);
  common.WriteConf(event, args_list, "base");

  console.log(args_list)

  // pyarmorを使用した場合distディレクトリにexhibition.pyが存在するのでoptionsで指定
  let pyshell = common.PyShell("base.py", args_list);

  pyshell.on("message", function (message) {
    message = common.toString(message);
    event.sender.send("log-create", message);
  });

  // DEBUG情報などを取得したい場合
  pyshell.on("stderr", function (message) {
    common.ErrorLog(event, message);
  });

  pyshell.end(function (err, code, signal) {
    if (err) throw err;
    // 処理が終了した時に、設定情報を再度反映させる
    common.LoadConf(event, "base");
    event.sender.send("log-create", "処理は全て終了しました");
  });
}


module.exports = {IPCInitialize}
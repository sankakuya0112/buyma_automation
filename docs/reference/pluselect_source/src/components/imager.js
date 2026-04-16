/**********************************
*   画像編集スクリプト
*   XXXX IPC CONNECTION XXXX
*
* 初期化
* init-imager
*
* ディレクトリ選択
* open-file-imager -> OpenFileImager(event)
*
* ファイルを開く
* open-file -> OpenFile(event, value)
*
* 画像編集開始
* start-imager -> StartImager(event, args_list)
**********************************/

// requires
const {ipcMain, dialog} = require("electron");
const fs = require("fs");
const path = require("path");
const src_dir = path.dirname(__dirname)

//requires components
const common = require("./common.js");

global.imager_key = "";


function IPCInitialize () {
  ipcMain.on("init-imager", (event) => {
    common.LoadConf(event, "imager");
    image_dir_select(event);
  });

  ipcMain.on("open-file-imager", (event) => {
    OpenFileImager(event)
  })

  ipcMain.on("open-file", (event, value) => {
    OpenFile(event, value)
  })

  ipcMain.on("start-imager", (event, args_list) => {
    StartImager(event, args_list)
  })
}

function OpenFileImager(event) {
  dialog
    .showOpenDialog({
      properties: ["openDirectory"],
    })
    .then((folder) => {
      if (folder.filePaths[0]) {
        // 選択したフォルダ配下のディレクトリを表示させる
        console.log(folder.filePaths[0]);
        image_dir_select(event, folder.filePaths[0]);
      }
    });
}

function image_dir_select(event) {
  try {
    fs.statSync(dir_data);
    console.log(dir_data + "の中のフォルダを開きます。");
    event.sender.send("selected-directory", dir_data);
    // ディレクトリ選択ボタン
    fs.readdir(dir_data, function (err, list) {
      if (err) {
        console.log(err);
      } else {
        var dir_list = [];
        for (var i = 0; i < list.length; i++) {
          var dir_check = fs
            .statSync(path.join(dir_data, list[i]))
            .isDirectory();
          if (dir_check) {
            dir_list.push(list[i]);
          }
        }
        event.sender.send("make-dir-button", dir_list);
      }
    });
  } catch (error) {
    console.log(error);
    dialog.showErrorBox(
      "BUYMAフォルダの場所に関するエラー",
      "Desktopがクラウドに存在していると上手く動かないことがあります。\n" +
        dir_data +
        "\n\n↓↓↓エラー内容↓↓↓\n" +
        error
    );
  }
}

function OpenFile(event, value) {
  console.log(value);
  dialog
    .showOpenDialog({
      properties: ["openFile"],
    })
    .then((file) => {
      if (file.filePaths[0]) {
        event.sender.send(value, file.filePaths[0]);
      }
    });
}

function StartImager(event, args_list) {
  // confを更新する
  args_list = JSON.parse(args_list);
  common.WriteConf(event, args_list, "imager");

  // 追加要素
  args_list["imager_key"] = imager_key;
  args_list["electron_dir"] = src_dir;

  // pyarmorを使用した場合distディレクトリにexhibition.pyが存在するのでoptionsで指定
  let pyshell = common.PyShell("imager.py", args_list);

  pyshell.on("message", function (message) {
    message = common.toString(message);
    // ログイン情報を保存
    if (message === "one time login key ***imager***") {
      imager_key = message;
    } else {
      event.sender.send("log-create", message);
    }
    // 作成した画像を表示させる
    if (message.indexOf("image.png") !== -1) {
      var image_path = message.slice(message.indexOf("：") + 1);
      event.sender.send("disp-image", image_path);
    }
  });

  // DEBUG情報などを取得したい場合
  pyshell.on("stderr", function (message) {
    common.ErrorLog(event, message);
  });

  pyshell.end(function (err, code, signal) {
    if (err) throw err;
    // 処理が終了した時に、設定情報を再度反映させる
    common.LoadConf(event, "imager");
    event.sender.send("log-create", "処理は全て終了しました");
  });
}

module.exports = {IPCInitialize}
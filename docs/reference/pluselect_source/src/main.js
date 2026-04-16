// requires
const {app, BrowserWindow, Menu, dialog, ipcMain} = require("electron");
const path = require("path");
const src_dir = __dirname
// requires components
const unzip = require("node-unzip-2");
const request = require("request");
const fs = require("fs");
const ProgressBar = require("electron-progressbar");


// Components modules
// const WindowComponents = require('./components/window.js')
const BaseComponents = require('./components/base.js')
const ImagerComponents = require('./components/imager.js')
const ScraperComponents = require('./components/scraper.js')
const CommonCompnents = require('./components/common.js')
const ExhibitionComponents = require('./components/exhibition.js')
const ManagerComponents = require('./components/manager.js')
const StockComponents = require('./components/stock.js')

// win mac関係なく、BUYMAディレクトリのPATHが取れる
dir_home = process.env[process.platform == "win32" ? "USERPROFILE" : "HOME"];
dir_buyma = path.join(dir_home, "Desktop", "BUYMA");
dir_account = path.join(dir_buyma, "account")
dir_data = path.join(dir_buyma, "data");
dir_image_conf = path.join(dir_buyma, "conf", "image.conf");
dir_manager_conf = path.join(dir_buyma, "conf", "manager.conf");
dir_scraping_conf = path.join(dir_buyma, "conf", "scraping.conf");
dir_base_conf = path.join(dir_buyma, "conf", "base.conf");

// constants
const os_info = process.platform;

//■■■■■■■■■■■■■■■■■■■■■■■■■■
// ウィンドウ初期化処理
//■■■■■■■■■■■■■■■■■■■■■■■■■■
//  初期化が完了した時の処理
app.on("ready", () => {
  mainWindow = createWindow();
});

// 全てのウィンドウが閉じたときの処理
app.on("window-all-closed", () => {
  // macOSのとき以外はアプリケーションを終了させます
  if (process.platform !== "darwin") {
    app.quit();
  } else {
    app.quit();
  }
});

// アプリケーションがアクティブになった時の処理(Macだと、Dockがクリックされた時）
app.on("activate", () => {
  // メインウィンドウが消えている場合は再度メインウィンドウを作成する
  if (mainWindow === null) {
    mainWindow = createWindow();
  }
});

//■■■■■■■■■■■■■■■■■■■■■■■■■■
// ページ遷移
//■■■■■■■■■■■■■■■■■■■■■■■■■■
ipcMain.on("change-to-exhibition", (event) => {
  mainWindow.loadFile(path.join(__dirname, "public", "exhibition.html"));
});

ipcMain.on("change-to-manager", (event) => {
  mainWindow.loadFile(path.join(__dirname, "public", "manager.html"));
});

ipcMain.on("change-to-scraper", (event) => {
  mainWindow.loadFile(path.join(__dirname, "public", "scraper.html"));
});

ipcMain.on("change-to-imager", (event) => {
  mainWindow.loadFile(path.join(__dirname, "public", "imager.html"));
});


//■■■■■■■■■■■■■■■■■■■■■■■■■■
// Window
//■■■■■■■■■■■■■■■■■■■■■■■■■■
function createWindow() {
  // メインウィンドウを作成します
  mainWindow = new BrowserWindow({
    webPreferences: {
      nodeIntegration: true,
    },
    width: 1350,
    height: 750,
    // frame: false,
  });

  mainWindow.setMenu(null);

  // メインウィンドウに表示するURLを指定します
  mainWindow.loadFile(path.join(src_dir, "public", "exhibition.html"));
  initWindowMenu();

  // デベロッパーツールの起動
  // mainWindow.webContents.openDevTools()

  // First Check
  if (fs.existsSync(dir_buyma)) {
    console.log("BUYMAディレクトリは存在します。");
  } else {
    dialog.showErrorBox(
      "BUYMAフォルダがDesktopに存在しないか、正しくありません。",
      "こちらを参考にフォルダを作成してください。\nWindows：https://youtu.be/Dhyboyc3nbI?t=130\nMac：https://youtu.be/vw5tYmVHc9o?t=105\n\nこちらのエラーは「One Drive」や「icloud」などクラウドサービスの中にデスクトップが置かれている場合にも表示されます。\nその場合はシステムは不安定になりますが、そのまま使える場合もございます。"
    );
  }

  // メインウィンドウが閉じられたときの処理
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  return mainWindow;
}

function initWindowMenu () {
  const isMac = process.platform === "darwin";

  const template = [
    // { role: 'appMenu' }
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: "about" },
              { type: "separator" },
              { role: "services" },
              { type: "separator" },
              { role: "hide" },
              { role: "hideothers" },
              { role: "unhide" },
              { type: "separator" },
              { role: "quit" },
            ],
          },
        ]
      : []),
    // { role: 'fileMenu' }
    {
      label: "ファイル",
      submenu: [isMac ? { role: "close" } : { role: "quit" }],
    },
    // { role: 'editMenu' }
    {
      label: "編集",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        ...(isMac
          ? [
              { role: "pasteAndMatchStyle" },
              { role: "delete" },
              { role: "selectAll" },
              { type: "separator" },
              {
                label: "Speech",
                submenu: [{ role: "startspeaking" }, { role: "stopspeaking" }],
              },
            ]
          : [{ role: "delete" }, { type: "separator" }, { role: "selectAll" }]),
      ],
    },
    // { role: 'viewMenu' }
    {
      label: "表示",
      submenu: [
        { role: "reload" },
        { role: "forcereload" },
        { role: "toggledevtools" },
        { type: "separator" },
        { role: "resetzoom" },
        { role: "zoomin" },
        { role: "zoomout" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    // { role: 'windowMenu' }
    {
      label: "ウィンドウ",
      submenu: [
        { role: "minimize" },
        { role: "zoom" },
        ...(isMac
          ? [
              { type: "separator" },
              { role: "front" },
              { type: "separator" },
              { role: "window" },
            ]
          : [{ role: "close" }]),
      ],
    },
    {
      label: "システム",
      submenu: [
        {
          label: "アップデート",
          click() {
            AutoUpdater();
          },
        },
        {
          label: "強制アップデート",
          click() {
            StartUpdate("Force Update", "Force Update");
          },
        },
        {
          label: "終了",
          click() {
            app.quit();
          },
        },
        {
          label: "BASE自動システム",
          click() {
            mainWindow.loadFile(path.join(src_dir, "public", "base.html"));
          },
        },
        {
          label: "在庫管理システム",
          click() {
            mainWindow.loadFile(
              path.join(src_dir, "public", "stockcheck.html")
            );
          },
        },
      ],
    },
    {
      label: "リンク",
      submenu: [
        {
          label: "PLUSELECT Webページ",
          click() {
            mainWindow.loadURL("https://pluselect.com/");
          },
        },
        {
          label: "お問い合わせ",
          click() {
            mainWindow.loadURL("mailto:pluselect.2019@gmail.com");
          },
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}


//■■■■■■■■■■■■■■■■■■■■■■■■■■
// アップデーター
//■■■■■■■■■■■■■■■■■■■■■■■■■■
function StartUpdate(current_version, new_version) {
  var progressBar = new ProgressBar({
    closeOnComplete: false,
    text:
      "アップデートを実行" +
      current_version.toString() +
      "=>" +
      new_version.toString(),
    detail: "新しいファイルをダウンロードしています...",
    browserWindow: {
      closable: true,
      webPreferences: {
        nodeIntegration: true,
      },
      height: 250,
    },
  });
  progressBar.on("completed", function () {
    console.info(`completed...`);
    progressBar.title = "Finished";
    progressBar.detail =
      "重要※アプリを再起動してください！\nアップデートは正常に終了しました " +
      current_version.toString() +
      "=>" +
      new_version.toString();
  });
  console.log(progressBar.detail);
  // ZIPファイルをGithubからダウンロード
  new Promise((resolve, reject) => {
    console.log(path.join(src_dir, "..", "updater.zip"));
    try {
      request(
        {
          method: "GET",
          url: "https://github.com/plustry/Tool_Updater/archive/master.zip",
          encoding: null,
        },
        function (error, response, body) {
          console.log(response);
          if (!error && response.statusCode === 200) {
            fs.writeFileSync(
              path.join(src_dir, "..", "updater.zip"),
              body,
              "binary"
            );
            resolve("pass");
          }
        }
      );
    } catch (error) {
      progressBar.detail = "ツールは必ずデスクトップに置いてください。";
      reject("ツールは必ずデスクトップに置いてください。");
    }
  }).then(response => {
    new Promise((resolve, reject) => {
      // ZIPファイルを解凍
      progressBar.detail = "新しいファイルを展開しています...";
      var stream = fs
        .createReadStream(path.join(src_dir, "..", "updater.zip"))
        .pipe(unzip.Extract({ path: path.join(src_dir, "..") }));
      stream.on("close", function () {
        resolve("pass");
      });
    }).then(response => {
      // ディレクトリを移動
      try {
        progressBar.detail =
          "古いファイルを削除しています...\n5分以上経過しても終了しない場合はPCを再起動してもう一度お確かめください。";
        var update_list = fs.readdirSync(
          path.join(src_dir, "..", "Tool_Updater-master")
        );
        console.log(update_list);

        for (let i = 0; i < update_list.length; i++) {
          var update_path = path.join(src_dir, "..", update_list[i]);
          // console.log(update_path, fs.statSync(update_path).isDirectory())
          if (fs.statSync(update_path).isDirectory()) {
            deleteFolderRecursive(update_path);
          } else {
            fs.unlinkSync(update_path);
          }
          fs.renameSync(
            path.join(
              path.join(src_dir, "..", "Tool_Updater-master"),
              update_list[i]
            ),
            update_path
          );
        }
        progressBar.detail = "新しいファイルを適用しています...";
        if (os_info == "darwin") {
          fs.chmodSync(
            path.join(src_dir, "chromedriver", "chromedriver"),
            0o777
          );
        }
        // ZIPファイルを削除
        fs.unlinkSync(path.join(src_dir, "..", "updater.zip"));
        // 展開ディレクトリを削除
        deleteFolderRecursive(
          path.join(src_dir, "..", "Tool_Updater-master")
        );
        progressBar.detail =
          "アップデートに成功しました。\nアプリを再起動してください！";
        progressBar.setCompleted();
      } catch (error) {
        var message = error.message;
        if (error.message.indexOf("EPERM") != -1) {
          message =
            "アップデートに失敗しました。ファイルが別の場所で開かれているか、chromedriverがバックグラウンドで動いている可能性があります。https://drive.google.com/file/d/1kfrWoGcz4mhmBkOdb77HixiMHjdm6b08/view";
        } else if (error.massage.indexOf("ENOENT") != -1) {
          message =
            "アップデートに失敗しました。前回のアップデートが途中で終わった可能性があります。再度「強制アップデート」をお試しください。";
        }
        progressBar.detail = massage;
        progressBar.setCompleted();
      }
    });
  });
}

function AutoUpdater(event) {
  // 最新バージョンをGithubから確認
  process.on("unhandledRejection", console.dir);
  const url_req = new Promise((resolve, reject) => {
    request("https://plustry.github.io/Tool_Updater/versions", function (
      error,
      response,
      body
    ) {
      resolve(body);
    });
  }).then((new_version) => {
    console.log(new_version);
    // 保存されたファイルから現在のバージョンを確認
    let current_version = fs
      .readFileSync(path.join(src_dir, "..", "versions.html"), "utf-8")
      .toString();
    console.log(current_version);
    var detail_txt = "";
    if (new_version == current_version) {
      detail_txt =
        "アップデートはありませんでした Ver: " + new_version.toString();
      var options_ = {
        type: "info",
        title: "アップデート終了",
        message: "アップデートは終了しました",
        detail: detail_txt,
      };
      dialog.showMessageBox(mainWindow, options_);
    } else {
      StartUpdate(current_version, new_version);
    }
  });
}

// ディレクトリ削除
var deleteFolderRecursive = function (pathe) {
  if (fs.existsSync(pathe)) {
    fs.readdirSync(pathe).forEach(function (file) {
      var curPath = path.join(pathe, file);
      if (fs.statSync(curPath).isDirectory()) {
        //recurse
        deleteFolderRecursive(curPath);
      } else {
        //delete file
        fs.unlinkSync(curPath);
      }
    });
    fs.rmdirSync(pathe);
  }
};


BaseComponents.IPCInitialize()
ImagerComponents.IPCInitialize()
ScraperComponents.IPCInitialize()
CommonCompnents.IPCInitialize()
ExhibitionComponents.IPCInitialize()
ManagerComponents.IPCInitialize()
StockComponents.IPCInitialize()
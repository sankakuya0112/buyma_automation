/**********************************
* 共通モジュールスクリプト
* 
* エラーログ表示
* ErrorLog(event, message) -> null
*
* 設定ファイル読み込み
* LoadConf(event, which_conf) -> null
*
* 設定ファイル書き込み
* WriteConf(event, args_list, which_conf) -> null
*
* CSVファイルの読み込み
* readCSV(path) -> csv object
* 
* テキストファイルの読み込み
* readTXT(path) -> txt object
* 
* ファイルが存在しているか
* isExistFile(file) -> Bool
* 
* 文字列デコード(Windowsのみ)
* toString(bytes) -> bytes
*
* Pythonインスタンス作成
* PyShell(filename, args) -> PythonShell Object
**********************************/

// requires
const {ipcMain, dialog} = require("electron");
const path = require("path");
const fs = require("fs");
const {PythonShell} = require("python-shell");
const Encoding = require("encoding-japanese");
const csvSync = require("csv-parse/lib/sync");
const src_dir = path.dirname(__dirname)
const tool_dir = path.dirname(src_dir)

// .envを読み込むための処理（これが無いとprocess.envが使えない）
const ENV_PATH = path.join(tool_dir, ".env");
require("dotenv").config({ path: ENV_PATH });

// builderだと階層が一つ上がる
if (__dirname.indexOf("app.asar") != -1) {
  python_script_dir = path.join(path.dirname(tool_dir), "python_scripts");
  // scrapyが読み込むパスを環境変数で指定
  process.env.PYTHONPATH = path.join(path.dirname(tool_dir), "scraping");
}else{
  python_script_dir = path.join(tool_dir, "python_scripts");
  // scrapyが読み込むパスを環境変数で指定
  process.env.PYTHONPATH = path.join(tool_dir, "scraping");
}

// constants
const os_info = process.platform;
if (os_info == "win32") {
  // builderだと階層が一つ上がる
  if (__dirname.indexOf("app.asar") != -1) {
    python_path = path.join(path.dirname(tool_dir), "python_modules", "bin", "python3");
  } else {
    python_path = path.join(tool_dir, "python_modules", "python.exe");
  }
} else if (os_info == "darwin") {
  // builderだと階層が一つ上がる
  if (__dirname.indexOf("app.asar") != -1) {
    python_path = path.join(path.dirname(tool_dir), "python_modules", "bin", "python3");
  } else {
    python_path = path.join(tool_dir, "python_modules", "bin", "python3");
  }
}

// .envからconfのkeyリストを取得
const imager_conf_list = process.env.imager_conf_list.split(",");
const scraper_conf_list = process.env.scraper_conf_list.split(",");
const manager_conf_list = process.env.manager_conf_list.split(",");

global.image_conf_data = {};
global.scraping_conf_data = {};
global.manager_conf_data = {};
global.base_conf_data = {};

function IPCInitialize() {
  // エラー表示用
  ipcMain.on("cause-error", (event, txt1, txt2) => {
    dialog.showErrorBox(txt1, txt2);
  });

  // 情報表示用
  ipcMain.on("show-info", (event, title, message, detail) => {
    let options = {
      type: "info",
      title: title,
      message: message,
      detail: detail,
    };
    dialog.showMessageBox(mainWindow, options);
  });
}

function ErrorLog(event, message) {
  var ErrorMessage = "";
  // var ErrorMessage = message
  if (message.indexOf("ModuleNotFoundError") !== -1) {
    ErrorMessage += message.substring(message.indexOf("ModuleNotFoundError"));
  } else if (message.indexOf("FileNotFoundError") !== -1) {
    ErrorMessage += message.substring(message.indexOf("FileNotFoundError"));
  } else if (message.indexOf("NotFoundError") !== -1) {
    ErrorMessage += message.substring(message.indexOf("NotFoundError"));
  } else if (message.indexOf("BrokenPipeError") !== -1) {
    ErrorMessage += message.substring(message.indexOf("BrokenPipeError"));
  }
  if (ErrorMessage) {
    // ErrorMessage += "\nエラーが発生しました！アップデートを試してください。\nhttps://docs.google.com/document/d/1wT88HLOaG2011eJn0V5u6gnzYjqLiTcRv6f7xHvvngY/edit#heading=h.k92avs7xmxcx"
    event.sender.send("log-create", ErrorMessage);
  }
}

/**********************************
* Confを読み込む
**********************************/
function LoadConf(event, which_conf) {
  var dir_conf = "";
  if (which_conf === "imager") {
    dir_conf = dir_image_conf;
  } else if (which_conf === "scraper") {
    dir_conf = dir_scraping_conf;
  } else if (which_conf === "manager") {
    dir_conf = dir_manager_conf;
  } else if (which_conf === "base") {
    dir_conf = dir_base_conf;
  }
  console.log("******", dir_conf)

  var conf_data = "";
  try {
    conf_data = readTXT(dir_conf)
  } catch (error) {
    event.sender.send(
      "log-create",
      dir_conf + "：こちらにファイルを置くと設定情報が保存されます。"
    );
  }

  // image_conf_dataを設定
  if (which_conf === "imager") {
    try {
      image_conf_data = JSON.parse(conf_data);
      event.sender.send("load-image-conf", conf_data);
    } catch (error) {
      event.sender.send("log-create", "image.confの読み込みに失敗しました。");
    }
  }
  // scraping_conf_dataを設定
  else if (which_conf === "scraper") {
    try {
      scraping_conf_data = JSON.parse(conf_data);
      event.sender.send("load-scraping-conf", conf_data);
    } catch (error) {
      event.sender.send(
        "log-create",
        "scraping.confの読み込みに失敗しました。"
      );
    }
  } 
  // manager_conf_dataを設定
  else if (which_conf === "manager") {
    try {
      manager_conf_data = JSON.parse(conf_data);
      event.sender.send("load-manager-conf", conf_data);
    } catch (error) {
      event.sender.send("log-create", "manager.confの読み込みに失敗しました。");
    }
  }
  // base_conf_dataを設定
  else if (which_conf === "base") {
    try {
      base_conf_data = JSON.parse(conf_data);
      event.sender.send("load-base-conf", conf_data);
    } catch (error) {
      event.sender.send("log-create", "base.confの読み込みに失敗しました。");
    }
  }
}

/**********************************
* Confを書き込む
**********************************/
function WriteConf(event, args_list, which_conf) {
  var dir_conf = "";
  if (which_conf === "imager") {
    dir_conf = dir_image_conf;
  } else if (which_conf === "scraper") {
    dir_conf = dir_scraping_conf;
  } else if (which_conf === "manager") {
    dir_conf = dir_manager_conf;
  } else if (which_conf === "base") {
    dir_conf = dir_base_conf;
  }

  var conf_data = "";
  if (which_conf === "imager") {
    conf_data = image_conf_data;
  } else if (which_conf === "scraper") {
    conf_data = scraping_conf_data;
  } else if (which_conf === "manager") {
    conf_data = manager_conf_data;
  } else if (which_conf === "base") {
    conf_data = base_conf_data;
  }

  // image_conf_dataのメアドとパスワードを更新
  conf_data["login"] = {};
  conf_data["login"]["email"] = args_list["email"];
  conf_data["login"]["password"] = args_list["password"];

  // spider名を取得
  var spider_name = "";
  if (which_conf === "imager") {
    if (args_list["choiced_dir"].indexOf("_") !== -1) {
      spider_name = args_list["choiced_dir"].substring(
        0,
        args_list["choiced_dir"].indexOf("_")
      );
    }
  } else if (which_conf === "scraper") {
    spider_name = args_list["crawler_or_spidercls"];
  } else if (which_conf === "manager") {
    onoff = args_list["onoff"];
  }

  // 初めて設定するspiderの場合
  if (which_conf === "imager" || which_conf === "scraper") {
    if (Object.keys(conf_data).indexOf(spider_name) === -1) {
      conf_data[spider_name] = {};
    }
  } else if (which_conf === "manager") {
    if (Object.keys(conf_data).indexOf(onoff) === -1) {
      conf_data[spider_name] = {};
    }
  }

  var conf_list = {};
  if (which_conf === "imager") {
    // カテゴリとスパイダー名を取得
    var category = "";
    if (args_list["img_new_category"]) {
      category = args_list["img_new_category"];
    } else if (args_list["img_category"]) {
      category = args_list["img_category"];
    }
    // カテゴリのパラメータを更新
    imager_conf_list.forEach(e => {
      conf_list[e] = args_list[e];
    })
    conf_data[spider_name][category] = conf_list;
  } else if (which_conf === "scraper") {
    scraper_conf_list.forEach(e => {
      conf_list[e] = args_list[e];
    })
    conf_data[spider_name] = conf_list;
  } else if (which_conf === "manager") {
    manager_conf_list.forEach(e => {
      conf_list[e] = args_list[e];
    })
    conf_data[onoff] = conf_list;
  }

  // 書き出し
  writeTXT(dir_conf, JSON.stringify(conf_data))
  .then(res => {
    if(res){
      console.log(which_conf + "のconfファイルを保存しました。");
    }else{
      console.log(which_conf + "のconfファイルを保存できませんでした。");
    }
  })
}


/**********************************
* file関係の操作関数
**********************************/
function readCSV(path) {
  let data = fs.readFileSync(path);
  let res = csvSync(data);
  return res;
}

function readTXT(path) {
  let res = fs.readFileSync(path, { encoding: "utf-8" });
  return res;
}

function writeTXT(path, text) {
  return new Promise(resolve => {
    fs.writeFile(path, text, "utf8", (err) => {
      if (err) {
        resolve(false);
      } else {
        resolve(true);
      }
    });
  })
}

function isExistFile(file) {
  try {
    fs.statSync(file);
    return true;
  } catch (err) {
    if (err.code === "ENOENT") return false;
  }
}

/**********************************
* byte -> string
**********************************/
function toString(bytes) {
  if (os_info == "win32") {
    return Encoding.convert(bytes, {
      from: "SJIS",
      to: "UNICODE",
      type: "string",
    });
  } else if (os_info == "darwin") {
    return bytes;
  }
};


/**********************************
* python shell
**********************************/
function PyShell(filename, args) {
  let options = {
    mode: "text",
    pythonPath: python_path,
    scriptPath: python_script_dir,
    pythonOptions: ["-u"],
    args: JSON.stringify(args),
    encoding: "binary",
  };

  // Macのときはエンコーディングする必要がない
  if (os_info == "darwin") {
    delete options["encoding"];
  }

  // pyarmorを使用した場合distディレクトリにexhibition.pyが存在するのでoptionsで指定
  console.log(options);
  let pyshell = new PythonShell(filename, options)
  return pyshell;
}

module.exports = {IPCInitialize, ErrorLog, LoadConf, WriteConf, readCSV, readTXT, isExistFile, toString, PyShell}
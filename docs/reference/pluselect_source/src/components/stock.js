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
const {ipcMain} = require("electron");
const fs = require("fs");
const dateformat = require('dateformat');
const path = require("path");
const src_dir = path.dirname(__dirname)
const createCsvWriter = require('csv-writer').createObjectCsvWriter;

// require components
const common = require('./common.js')

// Set Date
const now = new Date();
const today = dateformat(now, 'yyyymmddHHMM')

const dir_home = process.env[process.platform == "win32" ? "USERPROFILE" : "HOME"];
const dir_buyma = path.join(dir_home, "Desktop", "BUYMA");
const dir_syuppin = path.join(dir_buyma, "syuppin");

global.scraper_key = "";

function IPCInitialize() {
  ipcMain.on("init-stockcheck", (event) => {
    InitStockCheck(event)
  })
  ipcMain.on("start-create-list", (event, args_list) => {
    StartCreateList(event, args_list)
  })
  ipcMain.on("start-stockcheck", (event, args_list) => {
    StartStockCheck(event, args_list)
  })
  ipcMain.on("start-stock-reflect", (event, args_list) => {
    StartStockReflect(event, args_list)
  })
}

function InitStockCheck(event) {
  try {
    fs.statSync(dir_buyma);
    console.log("デフォルトフォルダが存在したので開きます。");
    event.sender.send("selected-directory", dir_buyma);
  } catch (error) {
    console.log(error);
  }
  // パラメータが存在すれば読み込む
  common.LoadConf(event, "scraper");
}

// 在庫確認開始
function StartCreateList(event, args_list) {
  // 認証チェック
  if (scraper_key !== "one time login key ***scraper***") {
    event.sender.send("log-create", "認証が完了していません。");
    return;
  }
  args_list = JSON.parse(args_list);
  var csv_path = args_list["csv_path"]
  event.sender.send("log-create", csv_path);
  readDictCSV(csv_path).then(async csv_data => {
    // 出品中のitem_idのリスト
    var item_id_list = []
    await Promise.all(
      csv_data.map(async row => {
        item_id_list.push(row["item_id"])
      })
    )
    console.log(item_id_list)

    // syuppinフォルダの中のcsvリストを取得
    getDirCsvList(dir_syuppin).then(async dirfile_csv_list => {
      // 新しい出品リスト
      var new_syuppin_list = []
      // 同期処理！！
      await Promise.all(
        dirfile_csv_list.map(async csv_name => {
          console.log(csv_name)
          // csvを読み込んでデータを作成
          var data = await readDictCSV(path.join(dir_syuppin, csv_name))
          await Promise.all(
            data.map(async x => {
              if(item_id_list.indexOf(x["item_id"]) !== -1){
                // CSVを出力用に整える(stockのcsvを読み込んだ場合)
                if(x["after_size"]){
                  x["size"] = x["after_size"]
                }
                if(x["after_price"]){
                  x["item_no_cur_price"] = x["after_price"]
                }
                if(x["after_sell_price"]){
                  x["item_sell_price"] = x["after_sell_price"]
                }
                new_syuppin_list.push(x)
              }
            })
          )
        })
      )
      console.log(new_syuppin_list)
      if(new_syuppin_list.length === 0){
        event.sender.send("log-create", "syuppinフォルダにマッチする商品はありませんでした。");
      }

      // spider毎に出力
      var spider_dict = {}
      // urlのドメインで分割
      await Promise.all(
        new_syuppin_list.map(async data => {
          var spider = data["item_url"]
          spider = spider.substring(spider.indexOf("//") + 2)
          spider = spider.substring(0, spider.indexOf("/"))
          spider = spider.substring(0, spider.lastIndexOf("."))
          spider = spider.substring(spider.lastIndexOf(".") + 1)
          if(Object.keys(spider_dict).indexOf(spider) === -1){
            spider_dict[spider] = []
            spider_dict[spider].push(data)
          }else{
            spider_dict[spider].push(data)
          }
        })
      )
      console.log(spider_dict)

      var csv_header = [
        {id: 'item_img_folder', title: 'item_img_folder'},
        {id: 'item_name', title: 'item_name'},
        {id: 'item_brand', title: 'item_brand'},
        {id: 'item_model', title: 'item_model'},
        {id: 'item_category', title: 'item_category'},
        {id: 'item_comment', title: 'item_comment'},
        {id: 'item_size_color', title: 'item_size_color'},
        {id: 'item_deadline', title: 'item_deadline'},
        {id: 'item_url', title: 'item_url'},
        {id: 'item_buyplace', title: 'item_buyplace'},
        {id: 'item_shop', title: 'item_shop'},
        {id: 'item_sendplace', title: 'item_sendplace'},
        {id: 'color', title: 'color'},
        {id: 'size', title: 'size'},
        {id: 'item_season', title: 'item_season'},
        {id: 'item_tag', title: 'item_tag'},
        {id: 'item_thema', title: 'item_thema'},
        {id: 'item_sell_price', title: 'item_sell_price'},
        {id: 'item_pub_price', title: 'item_pub_price'},
        {id: 'item_delivery', title: 'item_delivery'},
        {id: 'item_stock', title: 'item_stock'},
        {id: 'item_sku', title: 'item_sku'},
        {id: 'item_duty', title: 'item_duty'},
        {id: 'item_memo', title: 'item_memo'},
        {id: 'item_price', title: 'item_price'},
        {id: 'item_currency', title: 'item_currency'},
        {id: 'item_no_cur_price', title: 'item_no_cur_price'},
        {id: 'item_deli_price', title: 'item_deli_price'},
        {id: 'item_vatoff', title: 'item_vatoff'},
        {id: 'vip_late', title: 'vip_late'},
        {id: 'duty', title: 'duty'},
        {id: 'item_profit', title: 'item_profit'},
        {id: 'item_keywords', title: 'item_keywords'},
        {id: 'item_topic', title: 'item_topic'},
        {id: 'item_image', title: 'item_image'},
        {id: 'kaiin_id', title: 'kaiin_id'},
        {id: 'item_id', title: 'item_id'},
      ]

      // spider毎に出力
      Object.keys(spider_dict).forEach(key => {
        var csv_path = path.join(dir_syuppin, key + "_" + today + ".csv")
        createDictCSV(spider_dict[key], csv_path, csv_header)
      })
      event.sender.send("log-create", "処理は全て終了しました");
    })
  })
}

// ファイル読み込み用
function createDictCSV(data, output_path, csv_header) {
  // 準備
  const csvWriter = createCsvWriter({
    path: output_path,
    header: csv_header
  });
  // 書き込み
  csvWriter.writeRecords(data)
  .then(() => {
    console.log('done');
  });
}

// ファイル読み込み用
function readDictCSV(path) {
  // Customerを編集
  return new Promise(function (resolve) {
    fs.readFile(path, "utf-8", (err, data) => {
      if (err) throw err;
      const res_data = common.readCSV(path);
      // csvのheaderを取得
      const header = res_data[0]
      // res_data[0]を削除
      res_data.shift()
      // dictに変換
      var csv_data = []
      res_data.forEach(row =>{
        var csv_raw = {}
        for (var i = 0; i < header.length; i++) {
          csv_raw[header[i]] = row[i]
        }
        csv_data.push(csv_raw)
      })
      resolve(csv_data)
    });
  })
}

function getDirCsvList(dir_syuppin) {
  // Customerを編集
  return new Promise(function (resolve) {
    try {
      fs.statSync(dir_syuppin);
      console.log(dir_syuppin + "の中のフォルダを開きます。");
      // ディレクトリ&ファイル選択ボタン
      fs.readdir(dir_syuppin, function (err, list) {
        if (err) {
          console.log(err);
        } else {
          var dirfile_list = [];
          for (var i = 0; i < list.length; i++) {
            if (list[i].indexOf(".csv") !== -1) {
              dirfile_list.push(list[i]);
            }
          }
          resolve(dirfile_list);
        }
      });
    } catch (error) {
      resolve(error);
    }
  })
}

// 在庫確認開始
function StartStockCheck(event, args_list) {
  // 認証チェック
  if (scraper_key !== "one time login key ***scraper***") {
    event.sender.send("log-create", "認証が完了していません。");
    return;
  }
  // confを更新する
  args_list = JSON.parse(args_list);

  // pyarmorを使用した場合distディレクトリにexhibition.pyが存在するのでoptionsで指定
  let pyshell = common.PyShell("stock_check.py", args_list);

  pyshell.on("message", function (message) {
    message = common.toString(message);
    event.sender.send("log-create", message);
  });

  pyshell.on("stderr", function (message) {
    common.ErrorLog(event, message);
  });

  pyshell.end(function (err, code, signal) {
    if (err) throw err;
    event.sender.send("log-create", "処理は全て終了しました");
  });
}

// 在庫反映開始
function StartStockReflect(event, args_list) {
  // 認証チェック
  if (scraper_key !== "one time login key ***scraper***") {
    event.sender.send("log-create", "認証が完了していません。");
    return;
  }
  // confを更新する
  args_list = JSON.parse(args_list);
  args_list["electron_dir"] = src_dir;

  // pyarmorを使用した場合distディレクトリにexhibition.pyが存在するのでoptionsで指定
  let pyshell = common.PyShell("stock_reflect.py", args_list);

  pyshell.on("message", function (message) {
    message = common.toString(message);
    event.sender.send("log-create", message);
  });

  pyshell.on("stderr", function (message) {
    common.ErrorLog(event, message);
  });

  pyshell.end(function (err, code, signal) {
    if (err) throw err;
    event.sender.send("log-create", "処理は全て終了しました");
  });
}

module.exports = {IPCInitialize}
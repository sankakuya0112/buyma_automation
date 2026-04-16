// rendererとipc通信を行う
const { ipcRenderer, remote } = require("electron");
const path = require("path");
const { Menu, MenuItem } = remote;
global.checker = false;
global.keys_list = process.env.exhibition_conf_list.split(",");

// 右クリックメニュー
const menu = new Menu();
menu.append(
  new MenuItem({
    label: "コピー",
    accelerator: "CmdOrCtrl+C",
    role: "copy",
  })
);
menu.append(
  new MenuItem({
    label: "貼り付け",
    accelerator: "CmdOrCtrl+V",
    role: "paste",
  })
);

window.addEventListener(
  "contextmenu",
  (e) => {
    e.preventDefault();
    menu.popup({ window: remote.getCurrentWindow() });
  },
  false
);

// 動的に作成したボタンから呼び出してCSV読みこみ
function load_csv(obj) {
  // CSVファイル名を反映
  var csv_file_name = obj.options[obj.selectedIndex].value;
  document.getElementById("csv_name").value = csv_file_name;
  // CSVを読み込む
  var csv_file_path = path.join(document.getElementById("buyma_account_dir").value, csv_file_name)
  ipcRenderer.send("load-csv", csv_file_path);
}

// ページ遷移
const ChangeToExhibitionBtn = document.getElementById("exhibition");
ChangeToExhibitionBtn.addEventListener("click", (event) => {
  ipcRenderer.send("change-to-exhibition");
});
const ChangeToManagerBtn = document.getElementById("buymanager");
ChangeToManagerBtn.addEventListener("click", (event) => {
  ipcRenderer.send("change-to-manager");
});
const ChangeToScraperBtn = document.getElementById("scraper");
ChangeToScraperBtn.addEventListener("click", (event) => {
  ipcRenderer.send("change-to-scraper");
});
const ChangeToImagerBtn = document.getElementById("imager");
ChangeToImagerBtn.addEventListener("click", (event) => {
  ipcRenderer.send("change-to-imager");
});

// ストップ
// function stop() {
//   console.log('stop')
//   ipcRenderer.removeAllListeners('start')
// }

// アカウントディレクトリ新規作成
const makeDirBtn = document.getElementById("make-account-dir");
makeDirBtn.addEventListener("click", (event) => {
  var account_name = document.getElementById("account_name").value;
  if (!/^[A-Za-z0-9]+$/.test(account_name)) {
    ipcRenderer.send(
      "cause-error",
      "入力エラー",
      "アカウント名は半角英数字のみで入力してください"
    );
    return;
  }
  ipcRenderer.send("make-account-dir", account_name);
});

// フォルダ選択画面を呼び出し
const selectDirBtn = document.getElementById("choice_dir");
selectDirBtn.addEventListener("click", (event) => {
  ipcRenderer.send("open-file-exhibition");
});

// ログ画面
ipcRenderer.on("log-create", (event, log_text) => {
  document.getElementById("logs").innerHTML += "<p>[log]: " + log_text + "</p>";
  document.getElementById("footer").scrollTop = document.getElementById(
    "footer"
  ).scrollHeight;
});

// 自動出品開始
const StartBtn = document.getElementById("start-exhibition");
StartBtn.addEventListener("click", (event) => {
  if (!checker) {
    ipcRenderer.send("cause-error", "未設定項目", "CSVを選択してください");
    return;
  }

  // チェック
  let cookie = document.getElementById("cookie").value;
  let buyma_account_dir = document.getElementById("buyma_account_dir").value
  let csv_name = document.getElementById("csv_name").value
  if (
    cookie.indexOf("kaiin_id%22%3A") === -1 ||
    cookie.indexOf("%2C%22nickname") === -1 ||
    cookie.indexOf("_GEWZxdbe2H2bte4N") === -1
  ) {
    ipcRenderer.send(
      "cause-error",
      "設定エラー",
      "アクセスコードが正しくありません\n以下を参考にしてください。\nhttps://docs.google.com/document/d/1wT88HLOaG2011eJn0V5u6gnzYjqLiTcRv6f7xHvvngY/edit#heading=h.6gmd5ogn4qo7"
    );
    return;
  }else if (!buyma_account_dir) {
    ipcRenderer.send("cause-error", "未設定項目", "アカウントフォルダを選択してください。");
    return false;
  }else if(!csv_name){
    ipcRenderer.send("cause-error", "未設定項目", "CSVを選択してください。");
    return false;
  }
  
  var args_list = {
    buyma_account_dir: buyma_account_dir,
    csv_name: csv_name,
  };

  // edit_nameからは既に同じ名前でDBから取得できているので、キーを使い回して取得します
  for (let i = 0; i < keys_list.length; i++) {
    try {
      args_list[keys_list[i]] = document.getElementById(keys_list[i]).value;
    } catch (error) {
      console.log(error);
    }
  }
  console.log(args_list);
  ipcRenderer.send("start-exhibition", JSON.stringify(args_list));
});

// 選択したディレクトリを表示
ipcRenderer.on("selected-directory", (event, path) => {
  document.getElementById("buyma_account_dir").value = path;
});

// 選択したディレクトリに保存されたアクセスコードを表示
ipcRenderer.on("update-accesscode", (event, code) => {
  document.getElementById("cookie").value = code;
});

// 選択したcsvをボタンで表示
ipcRenderer.on("selected-csv", (event, fileList) => {
  // 選択したディレクトリからcsvだけピックアップしてボタンの作成
  var button_text =
    "<select onchange=load_csv(this)><option value=-1>フォルダを選択してください</option>";
  // var text_data = ""
  for (let index = 0; index < fileList.length; index++) {
    button_text +=
      "<option value=" + fileList[index] + ">" + fileList[index] + "</option>";
    // text_data += "<button onclick=load_csv('" + fileList[index] + "')>" + fileList[index] + "</button>"
  }
  button_text += "</select>";
  document.getElementById("csv_name").innerHTML = button_text;
});

// csvファイルの内容を表示
ipcRenderer.on("selected-filedata", (event, text_data) => {
  // ボタン分高さが変わるので自動調整
  AutoAdjust();
  document.getElementById("text-data").innerHTML = `${text_data}`;
  checker = true;
});

// パッディング自動調整
function AutoAdjust() {
  var padding = document.getElementsByClassName("csv-table")[0];
  padding.style.paddingTop = document.getElementsByTagName(
    "header"
  )[0].offsetHeight;
  padding.style.paddingBottom = document.getElementsByTagName(
    "footer"
  )[0].offsetHeight;
}

// ヘルプ項目
var txt1 = {
  account_name: "アカウントフォルダ新規作成",
  choice_dir: "アカウントフォルダを開く",
  day_score: "重複検査",
  hour_score: "重複検査",
  url_memo: "買い付け先メモ",
  csv_memo: "CSVのフォルダ名メモ",
  duplicate: "重複チェック",
  cookie: "アクセスコード",
  draft: "下書き",
  wait_time: "出品間隔",
};

var txt2 = {
  account_name:
    "新しいアカウントディレクトリを作成する場合、アカウント名を【半角英数字のみ】で入力して、ボタンを押してください。\nデスクトップにBUYMAディレクトリが作成され、その中のaccountディレクトリ内に新しく作成されます。",
  choice_dir:
    "出品するアカウントのディレクトリを選択します。\n事前にdataディレクトリからcsvと画像データを移動しておいてください。",
  day_score:
    "過去の出品との重複を検知します。\n指定した日付以降に出品されていた場合スキップされます。",
  hour_score:
    "過去の出品との重複を検知します。\n指定した日付以降に出品されていた場合スキップされます。",
  url_memo:
    "BUYMAの出品時に買い付け先メモを記入するかどうか選択できます。「on」か「off」かで記入してください。",
  csv_memo:
    "BUYMAの出品時にCSVのフォルダ名をメモに記入するかどうか選択できます。「on」か「off」かで記入してください。",
  duplicate:
    "BUYMAの出品時に重複チェックをするかどうか選択できます。「on」か「off」かで記入してください。",
  cookie:
    "Chromeから取得したアクセスコードを入力してください。\n詳しい取得方法は動画を参照してください。",
  draft:
    "BUYMAに下書き保存をするかどうか選択できます。「on」か「off」かで記入してください。",
  wait_time:
    "BUYMAに1品出品してから次の出品作業に移るまでの出品間隔を「秒」で設定できます。\n1分の場合は「60」と入力してください。",
};
// ヘルプボタン
function gethelp(key) {
  console.log(key);
  ipcRenderer.send("show-info", "ヘルプ", txt1[key], txt2[key]);
}

AutoAdjust();

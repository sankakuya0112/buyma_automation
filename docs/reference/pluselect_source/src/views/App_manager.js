// rendererとipc通信を行う
const { ipcRenderer, remote } = require("electron");
const { Menu, MenuItem } = remote;
global.manager_conf = "";

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

// デスクトップがあれば選択
ipcRenderer.send("init-manager");

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

// フォルダ選択画面を呼び出し
const selectDirBtn = document.getElementById("select_account_dir");
selectDirBtn.addEventListener("click", (event) => {
  ipcRenderer.send("open-file-manager");
});

// 選択したディレクトリを表示
ipcRenderer.on("selected-directory", (event, path) => {
  document.getElementById("account_dir").value = path;
});

// Manager開始
const StartBtn = document.getElementById("start-manager");
StartBtn.addEventListener("click", (event) => {
  if (document.getElementById("onoff").set2.value == "") {
    ipcRenderer.send(
      "cause-error",
      "未設定項目",
      "設定モードを選択してください"
    );
    return;
  }

  var args_list = {
    email: document.getElementById("email").value,
    password: document.getElementById("password").value,
    page_setting: document.getElementById("page_setting").set1.value,
    onoff: document.getElementById("onoff").set2.value,
    days: document.getElementById("days").value,
    buyma_account: document.getElementById("buyma_account").value,
    account_dir: document.getElementById("account_dir").value,
    access_prm: document.getElementById("access_prm").value,
    want_prm: document.getElementById("want_prm").value,
    cart_prm: document.getElementById("cart_prm").value,
    price_prm: document.getElementById("price_prm").value,
    maxprice_prm: document.getElementById("maxprice_prm").value,
    date_prm: document.getElementById("date_prm").value,
  };
  ipcRenderer.send("start-manager", JSON.stringify(args_list));
});

// ログ画面
ipcRenderer.on("log-create", (event, log_text) => {
  document.getElementById("logs").innerHTML += "<p>[log]: " + log_text + "</p>";
  document.getElementById("logs").scrollTop = document.getElementById(
    "logs"
  ).scrollHeight;
});

// パッディング自動調整
function AutoAdjust() {
  var padding = document.getElementsByClassName("manager-logs")[0];
  padding.style.paddingTop = document.getElementsByTagName(
    "header"
  )[0].offsetHeight;
}

// 設定データがあれば読み込み
ipcRenderer.on("load-manager-conf", (event, dic_list) => {
  if (dic_list) {
    manager_conf = JSON.parse(dic_list);
    document.getElementById("email").value = manager_conf["login"]["email"];
    document.getElementById("password").value =
      manager_conf["login"]["password"];
  } else {
    event.sender.send(
      "log-create",
      "BUYMA/conf フォルダにmanager.confファイルが無いまたは空です"
    );
  }
});

function load_conf(key) {
  var manager_data = "";
  if (manager_conf) {
    var manager_data = manager_conf[key];
    // GUIにconfデータを反映
    if (manager_data) {
      keys_list = Object.keys(manager_data);
      for (let i = 0; i < keys_list.length; i++) {
        let key = keys_list[i];
        try {
          document.getElementById(key).value = manager_data[key];
        } catch (error) {
          console.log(error);
        }
      }
    }
  }
}

// ヘルプ項目
var txt1 = {
  select_account_dir: "BUYMAアカウントフォルダ",
  page_choice: "ページ選択",
  onoff: "モード設定",
  buyma_account: "BUYMA アカウント名",
  days: "出品期限延長日数",
  access_prm: "アクセス数",
  want_prm: "お気に入り登録数",
  cart_prm: "カートに入れてる数",
  price_prm: "価格を割る数",
  maxprice_prm: "MAX価格スコア",
  date_prm: "経過日数を割る数",
};

var txt2 = {
  select_account_dir: "BUYMAアカウントフォルダを選択してください。(BUYMA/account)",
  page_choice: "Managerを適用するページを選択してください。",
  onoff: "商品情報をどのように変更するかを選択してください。",
  buyma_account:
    "適用したいアカウント名のフォルダを指定できます。\n空の場合はすべてのアカウントに対して実行します。",
  days: "出品の期限を延長する場合、日数を記入してください。",
  access_prm: "Managerのパラメーターに、設定した数×アクセス数を加えます。",
  want_prm: "Managerのパラメーターに、設定した数×お気に入り登録数を加えます。",
  cart_prm:
    "Managerのパラメーターに、設定した数×カートに入れてる数を加えます。",
  price_prm: "Managerのパラメーターに、価格÷設定した数を加えます。",
  maxprice_prm: "価格÷価格を割る数が大きくなる場合に、上限の閾値を設けます",
  date_prm: "Managerのパラメーターに、経過日数÷設定した数を引きます。",
};
// ヘルプボタン
function gethelp(key) {
  console.log(key);
  ipcRenderer.send("show-info", "ヘルプ", txt1[key], txt2[key]);
}

AutoAdjust();

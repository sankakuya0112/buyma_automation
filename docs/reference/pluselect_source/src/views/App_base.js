// rendererとipc通信を行う
const { ipcRenderer, remote } = require("electron");
const { Menu, MenuItem } = remote

// 右クリックメニュー
const menu = new Menu()
menu.append(new MenuItem({
  label: 'コピー',
  accelerator: 'CmdOrCtrl+C',
  role: 'copy'
}))
menu.append(new MenuItem({
  label: '貼り付け',
  accelerator: 'CmdOrCtrl+V',
  role: 'paste'
}))

window.addEventListener('contextmenu', (e) => {
  e.preventDefault()
  menu.popup({ window: remote.getCurrentWindow() })
}, false)

// 設定項目をすべて満たしているかどうか
global.keys_list = process.env.base_conf_list.split(",");
global.args_list = "";
global.base_conf = "";
global.choiced_dirfile = "";
// デフォルトフォルダを読み込む
ipcRenderer.send("init-base");

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
const selectDirBtn = document.getElementById("select-dir");
selectDirBtn.addEventListener("click", (event) => {
  ipcRenderer.send("open-file-imager");
});

// 選択したディレクトリを表示
ipcRenderer.on("selected-directory", (event, path) => {
  document.getElementById("data_dir").value = path;
});

// 選択されたディレクトリ内のフォルダをボタンにして表示
ipcRenderer.on("make-dirfile-button", (event, dirfile_list) => {
  var button_text =
    "<select onchange=choiceDirFile(this)><option value=-1>選択してください</option>";
  for (var i = 0; i < dirfile_list.length; i++) {
    button_text +=
      "<option value=" + dirfile_list[i] + ">" + dirfile_list[i] + "</option>";
  }
  button_text += "</select>";

  document.getElementById("dir-button").innerHTML = button_text;
  document.getElementById("dir-status").innerHTML =
    '<font color="red">ディレクトリを選択してください</font>';
});

// 設定データがあれば読み込み
ipcRenderer.on("load-base-conf", (event, dic_list) => {
  if (dic_list) {
    base_conf = JSON.parse(dic_list);
    document.getElementById("email").value = base_conf["login"]["email"];
    document.getElementById("password").value = base_conf["login"]["password"];
  } else {
    event.sender.send(
      "log-create",
      "BUYMA/conf フォルダにbase.confファイルが無いまたは空です"
    );
  }
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

// ディレクトリを選択した時にパラメータを反映
function choiceDirFile(obj) {
  choiced_dirfile = obj.options[obj.selectedIndex].value;
  document.getElementById("dir-status").innerHTML =
    '<font color="green">' + choiced_dirfile + "が選択されました</font>";
}

// ヘルプボタン
function gethelp(key) {
  console.log(key);
  ipcRenderer.send("show-info", "ヘルプ", txt1[key], txt2[key]);
}

// メイン編集開始
const MainStartBtn = document.getElementById("base-main");
MainStartBtn.addEventListener("click", (event) => {
  must_list = ["email", "password", "onoff"];

  for (var i = 0; i < must_list.length; i++) {
    if (document.getElementById(must_list[i]).value == "") {
      ipcRenderer.send(
        "cause-error",
        "未設定項目",
        must_list[i] + "を入力してください"
      );
      return;
    }
  }

  var args_list = {
    choiced_dirfile: choiced_dirfile,
    data_dir: document.getElementById("data_dir").value,
    email: document.getElementById("email").value,
    password: document.getElementById("password").value,
    onoff: document.getElementById("onoff").value,
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
  ipcRenderer.send("start-base", JSON.stringify(args_list));
});

// ヘルプ項目
var txt1 = {
  open_dir: "画像ディレクトリ",
  base_main: "編集実行",
  edit_mode: "モード",
};

var txt2 = {
  open_dir:
    "画像ディレクトリを指定してください。00002などの個別のディレクトリではなく、自動取得の際に指定したディレクトリを選択すると、csvごとのデータ選択ができるようになります。",
  base_main: "選択したフォルダにある画像を、モードで選択した条件で編集します。",
  edit_mode:
    "■テスト編集の場合：選択したフォルダの画像を3つだけ編集して画像の出来具合を確かめることができます。\n\n■全て編集の場合：選択したフォルダにある画像を全て編集します。\n\n■メイン画像の透過の場合：image000.pngを透過した画像をimage000_edit.pngという名前で保存します。\nimage000_edit.pngがある場合、その画像が一番前面にくる画像として使われるので、背景透過を綺麗にしたい場合は、ご自分の使い慣れている画像編集ソフトで背景を綺麗に透過させてご使用ください。",
};

AutoAdjust();
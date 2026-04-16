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
global.checker1 = false;
global.keys_list = process.env.imager_conf_list.split(",");
global.args_list = "";
global.choiced_category = "";
global.image_conf = "";
global.spider_name = "";
global.choiced_dir = "";
// デフォルトフォルダを読み込む
ipcRenderer.send("init-imager");

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

// ファイル選択呼び出し
const selectLogoBtn = document.getElementById("select-logo");
selectLogoBtn.addEventListener("click", (event) => {
  ipcRenderer.send("open-file", "selected-logo");
});
const selectFrameBtn = document.getElementById("select-frame");
selectFrameBtn.addEventListener("click", (event) => {
  ipcRenderer.send("open-file", "selected-frame");
});
const selectEffectBtn = document.getElementById("select-effect");
selectEffectBtn.addEventListener("click", (event) => {
  ipcRenderer.send("open-file", "selected-effect");
});
const selectBgBtn = document.getElementById("select-bg");
selectBgBtn.addEventListener("click", (event) => {
  ipcRenderer.send("open-file", "selected-bg");
});

// 選択されたファイルを適用
ipcRenderer.on("selected-logo", (event, path) => {
  document.getElementById("img_logo").value = path;
});
ipcRenderer.on("selected-frame", (event, path) => {
  document.getElementById("img_frame").value = path;
});
ipcRenderer.on("selected-effect", (event, path) => {
  document.getElementById("img_effect").value = path;
});
ipcRenderer.on("selected-bg", (event, path) => {
  document.getElementById("bg_image").value = path;
});

// 選択したディレクトリを表示
ipcRenderer.on("selected-directory", (event, path) => {
  document.getElementById("data_dir").value = path;
});

// 選択されたディレクトリ内のフォルダをボタンにして表示
ipcRenderer.on("make-dir-button", (event, dir_list) => {
  var button_text =
    "<select onchange=choiceDir(this)><option value=-1>フォルダを選択してください</option>";
  for (var i = 0; i < dir_list.length; i++) {
    button_text +=
      "<option value=" + dir_list[i] + ">" + dir_list[i] + "</option>";
  }
  button_text += "</select>";

  document.getElementById("dir-button").innerHTML = button_text;
  document.getElementById("dir-status").innerHTML =
    '<font color="red">ディレクトリを選択してください</font>';
  // 高さが変わるので自動パッディング
  AutoAdjust();
});

// 設定データがあれば読み込み
ipcRenderer.on("load-image-conf", (event, dic_list) => {
  if (dic_list) {
    image_conf = JSON.parse(dic_list);
    document.getElementById("email").value = image_conf["login"]["email"];
    document.getElementById("password").value = image_conf["login"]["password"];
  } else {
    event.sender.send(
      "log-create",
      "BUYMA/conf フォルダにimage.confファイルが無いまたは空です"
    );
  }
  // カテゴリーリストを更新
  ViewCategoryList();
});

// 生成された画像を表示してみる
ipcRenderer.on("disp-image", (event, image_path) => {
  var height =
    document.body.clientHeight -
    document.getElementsByTagName("main")[0].offsetHeight -
    document.getElementsByTagName("footer")[0].offsetHeight;
  // document.getElementById('logs').innerHTML += height
  document.getElementById("images").innerHTML +=
    '<img src ="file://' +
    image_path +
    "?" +
    Date.now() +
    '" height=' +
    height +
    "/>";
  document.getElementsByClassName("images")[0].style.height = height;
});

// ログ画面
ipcRenderer.on("log-create", (event, log_text) => {
  document.getElementById("logs").innerHTML += "<p>[log]: " + log_text + "</p>";
  document.getElementById("footer").scrollTop = document.getElementById(
    "footer"
  ).scrollHeight;
});

function ViewCategoryList() {
  var img_category_list = "";
  if (image_conf) {
    if (spider_name) {
      if (Object.keys(image_conf).indexOf(spider_name) !== -1) {
        spider_keys_list = Object.keys(image_conf[spider_name]);
        // console.log(spider_keys_list)
        for (var i = 0; i < spider_keys_list.length; i++) {
          img_category_list +=
            '<option value="' +
            spider_keys_list[i] +
            '">' +
            spider_keys_list[i] +
            "</option>";
        }
      }
    }
  }
  document.getElementById("img_category").innerHTML = img_category_list;
  document.getElementById("img_new_category").value = "";
  if (choiced_category) {
    document.getElementById("img_category").value = choiced_category;
  }
}

// パラメータ更新
function Reload_Prm(img_parameter) {
  // console.log(img_parameter)
  // htmlフォームのkeyに値を代入
  for (let i = 0; i < keys_list.length; i++) {
    try {
      // undefinedの場合はスキップする
      if (
        img_parameter[keys_list[i]] !== undefined &&
        img_parameter[keys_list[i]] !== ""
      ) {
        document.getElementById(keys_list[i]).value =
          img_parameter[keys_list[i]];
      }
    } catch {
      console.log("error");
    }
  }
  AutoAdjust();
}

// ディレクトリを選択した時にパラメータを反映
function choiceDir(obj) {
  choiced_dir = obj.options[obj.selectedIndex].value;
  document.getElementById("dir-status").innerHTML =
    '<font color="green">' + choiced_dir + "が選択されました</font>";

  // spider名を取得
  if (choiced_dir.indexOf("_") !== -1) {
    spider_name = choiced_dir.substring(0, choiced_dir.indexOf("_"));
  } else {
    spider_name = "";
  }

  // 初期パラメータを入力
  let img_parameter = "";
  if (image_conf) {
    if (spider_name) {
      if (Object.keys(image_conf).indexOf(spider_name) !== -1) {
        img_parameter = image_conf[spider_name][""];
        Reload_Prm(img_parameter);
      }
    }
  }

  // spiderのカテゴリーリストを反映
  ViewCategoryList();
  checker1 = true;
}

// カテゴリをクリックして、適用した時にパラメータを反映させる
function choiceCat() {
  choiced_category = document.getElementById("img_category").value;
  document.getElementById("img_category").value = choiced_category;
  img_parameter = "";
  if (image_conf) {
    if (spider_name) {
      if (choiced_category) {
        // choiced_categoryがあれば、新規の値を反映させる
        img_parameter = image_conf[spider_name][choiced_category];
        Reload_Prm(img_parameter);
      }
    }
  }
}

// ヘルプボタン
function gethelp(key) {
  console.log(key);
  ipcRenderer.send("show-info", "ヘルプ", txt1[key], txt2[key]);
}

// 最後に動的にパッディングする
function AutoAdjust() {
  padding = document.getElementsByTagName("main")[0];
  padding.style.paddingTop = document.getElementsByTagName(
    "header"
  )[0].offsetHeight;
}

// メイン編集開始
const MainStartBtn = document.getElementById("imager-main");
MainStartBtn.addEventListener("click", (event) => {
  // 画像ディスプレイをクリア
  document.getElementById("images").innerHTML = "";
  if (!checker1) {
    ipcRenderer.send("cause-error", "未設定項目", "フォルダを選択してください");
    return;
  }

  must_list = ["email", "password"];

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

  integer_list = [
    "image_diff",
    "item_name",
    "item_size",
    "item_move_y",
    "item_move_x",
    "logo_size",
    "logo_move_y",
    "logo_move_x",
    "bg_num",
    "bg_size",
    "back_move_y",
    "back_move_x",
    "addimg_1_name",
    "addimg_1_size",
    "addimg_1_y",
    "addimg_1_x",
    "addimg_2_name",
    "addimg_2_size",
    "addimg_2_y",
    "addimg_2_x",
    "addimg_3_name",
    "addimg_3_size",
    "addimg_3_y",
    "addimg_3_x",
  ];
  for (var i = 0; i < integer_list.length; i++) {
    let doc_data = document.getElementById(integer_list[i]).value;
    if (!/^[-]?([1-9]\d*|0)(\.\d+)?$/.test(doc_data) && doc_data !== "") {
      ipcRenderer.send(
        "cause-error",
        "入力エラー",
        txt1[integer_list[i]] + "の入力に数値以外の文字が有ります"
      );
      return;
    }
  }

  path_list = ["img_effect", "img_frame", "img_logo", "bg_image"];
  for (var i = 0; i < path_list.length; i++) {
    let doc_data = document.getElementById(path_list[i]).value;
    if (
      doc_data.indexOf("\\") === -1 &&
      doc_data.indexOf("/") === -1 &&
      doc_data !== ""
    ) {
      ipcRenderer.send(
        "cause-error",
        "入力エラー",
        txt1[path_list[i]] +
          "が正しくありません。\nファイルを開くで選択してください。"
      );
      return;
    }
  }

  var args_list = {
    choiced_dir: choiced_dir,
    data_dir: document.getElementById("data_dir").value,
    email: document.getElementById("email").value,
    password: document.getElementById("password").value,
    img_category: document.getElementById("img_category").value,
    img_new_category: document.getElementById("img_new_category").value,
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
  ipcRenderer.send("start-imager", JSON.stringify(args_list));
});

// ヘルプ項目
var txt1 = {
  open_dir: "画像ディレクトリ",
  logo_size: "ロゴサイズ",
  item_name: "メイン画像",
  item_size: "メイン画像サイズ",
  item_move_y: "メイン画像縦",
  item_move_x: "メイン画像横",
  back_move_y: "背景縦",
  back_move_x: "背景横",
  logo_move_y: "ロゴ縦",
  logo_move_x: "ロゴ横",
  bg_num: "背景画像番号",
  bg_size: "背景画像サイズ",
  back_move_y: "背景画像縦",
  back_move_x: "背景画像横",
  img_effect: "エフェクト画像",
  img_frame: "フレーム画像",
  img_logo: "ロゴ画像",
  img_category: "カテゴリ",
  img_new_category: "新規カテゴリ",
  "imager-main": "編集実行",
  image_diff: "透明度",
  bg_image: "指定背景PATH",
  edit_mode: "モード",
  addimg_1_name: "追加商品画像１",
  addimg_1_size: "追加商品画像１サイズ",
  addimg_1_y: "追加商品画像１縦",
  addimg_1_x: "追加商品画像１横",
  addimg_2_name: "追加商品画像２",
  addimg_2_size: "追加商品画像２サイズ",
  addimg_2_y: "追加商品画像２縦",
  addimg_2_x: "追加商品画像２横",
  addimg_3_name: "追加商品画像３",
  addimg_3_size: "追加商品画像３サイズ",
  addimg_3_y: "追加商品画像３縦",
  addimg_3_x: "追加商品画像３横",
};

var txt2 = {
  open_dir:
    "画像ディレクトリを指定してください。00002などの個別のディレクトリではなく、自動取得の際に指定したディレクトリを選択すると、csvごとのデータ選択ができるようになります。",
  logo_size:
    "ロゴの画像サイズです。\n生成画像サイズ以下の値にしてください。\n例（100）",
  item_name: "メイン画像の番号を指定してください。\n例（0）",
  item_size:
    "最前面に表示するメイン商品画像のサイズです。\n生成画像サイズ以下の値にしてください。",
  item_move_y:
    "メイン画像のたて移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、上ならマイナス、下ならプラスのピクセル値で入力してください。",
  item_move_x:
    "メイン画像のよこ移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、左ならマイナス、右ならプラスのピクセル値で入力してください。",
  back_move_y:
    "背景画像のたて移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、上ならマイナス、下ならプラスのピクセル値で入力してください。",
  back_move_x:
    "背景画像のよこ移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、左ならマイナス、右ならプラスのピクセル値で入力してください。",
  logo_move_y:
    "ロゴ画像のたて移動値です。デフォルト(0)のとき左上に表示されます。\n左上からの移動値を、上ならマイナス、下ならプラスのピクセル値で入力してください。",
  logo_move_x:
    "ロゴ画像のよこ移動値です。デフォルト(0)のとき左上に表示されます。\n左上からの移動値を、左ならマイナス、右ならプラスのピクセル値で入力してください。",
  bg_size: "背景画像サイズです。\n\n例（750）",
  back_move_y:
    "背景画像のたて移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、上ならマイナス、下ならプラスのピクセル値で入力してください。",
  back_move_x:
    "背景画像のよこ移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、左ならマイナス、右ならプラスのピクセル値で入力してください。",
  bg_num:
    "背景に使用する画像の番号です。\n存在しない場合、１ずつ小さくして再帰的に検索します。\n背景の欄に記入されている場合はそちらが優先されます。",
  img_effect:
    "エフェクト(背景画像に適用)の画像名を入力してください。\nフォルダは、dataフォルダと同じ階層のimg_content>effectを参照します。\n設定しない場合は空欄で大丈夫です。",
  img_frame:
    "フレーム(最前面に適用)の画像名を入力してください。\nフォルダは、dataフォルダと同じ階層のimg_content>frameを参照します。\n設定しない場合は空欄で大丈夫です。",
  img_logo:
    "ロゴ(最前面に適用)の画像名を入力してください。\nフォルダは、dataフォルダと同じ階層のimg_content>logoを参照します。\n設定しない場合は空欄で大丈夫です。",
  img_category:
    "以前カテゴリを作成したことがある場合、ここにそのカテゴリが表示されるので選択して「適用」をクリックしてください。\nよくわからない場合は右上の「自動画像加工ツール」をクリックして画面を再読み込みしてください。",
  img_new_category:
    "画像加工する時にシューズと服でパラメータを分けたい場合があると思います。\nそういった時はこちらにお好きなカテゴリを記入して頂き、実行してください。\n次回画面を再読み込みしましたら「カテゴリ」で選択可能。",
  "imager-main":
    "選択したフォルダにある画像を、モードで選択した条件で編集します。",
  image_diff:
    "透明化のパラメーターです。白背景ならば0.4~0.5, グレー背景なら0.1~0.2くらいがベストです。-1で透明化をスキップします。",
  bg_image:
    "背景(最背面に適用)の画像名を入力してください。\nフォルダは、dataフォルダと同じ階層のimg_content>backgroundを参照します。\n設定しない場合は空欄で大丈夫です。",
  edit_mode:
    "■テスト編集の場合：選択したフォルダの画像を3つだけ編集して画像の出来具合を確かめることができます。\n\n■全て編集の場合：選択したフォルダにある画像を全て編集します。\n\n■メイン画像の透過の場合：image000.pngを透過した画像をimage000_edit.pngという名前で保存します。\nimage000_edit.pngがある場合、その画像が一番前面にくる画像として使われるので、背景透過を綺麗にしたい場合は、ご自分の使い慣れている画像編集ソフトで背景を綺麗に透過させてご使用ください。",
  addimg_1_name: "さらに追加したい商品画像の番号を指定してください。\n例（4）",
  addimg_1_size:
    "追加の商品画像のサイズです。\n生成画像サイズ以下の値にしてください。\n例（300）",
  addimg_1_y:
    "追加の商品画像のたて移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、上ならマイナス、下ならプラスのピクセル値で入力してください。",
  addimg_1_x:
    "追加の商品画像のよこ移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、左ならマイナス、右ならプラスのピクセル値で入力してください。",
  addimg_2_name: "さらに追加したい商品画像の番号を指定してください。\n例（4）",
  addimg_2_size:
    "追加の商品画像のサイズです。\n生成画像サイズ以下の値にしてください。\n例（300）",
  addimg_2_y:
    "追加の商品画像のたて移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、上ならマイナス、下ならプラスのピクセル値で入力してください。",
  addimg_2_x:
    "追加の商品画像のよこ移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、左ならマイナス、右ならプラスのピクセル値で入力してください。",
  addimg_3_name: "さらに追加したい商品画像の番号を指定してください。\n例（4）",
  addimg_3_size:
    "追加の商品画像のサイズです。\n生成画像サイズ以下の値にしてください。\n例（300）",
  addimg_3_y:
    "追加の商品画像のたて移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、上ならマイナス、下ならプラスのピクセル値で入力してください。",
  addimg_3_x:
    "追加の商品画像のよこ移動値です。デフォルト(0)のとき中心に表示されます。\n中心からの移動値を、左ならマイナス、右ならプラスのピクセル値で入力してください。",
};

AutoAdjust();

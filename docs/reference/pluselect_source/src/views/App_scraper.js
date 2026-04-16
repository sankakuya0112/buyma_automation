// rendererとipc通信を行う
const { ipcRenderer, remote } = require("electron");
const { Menu, MenuItem } = remote;

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

// 設定項目をすべて満たしているかどうか
global.checker = false;
global.login = false;
global.scraping_conf = "";

// デフォルトフォルダを読み込む
ipcRenderer.send("init-scraper");

// 設定データがあれば読み込み
ipcRenderer.on("load-scraping-conf", (event, dic_list) => {
  // console.log(dic_list)
  scraping_conf = JSON.parse(dic_list);
  var email = scraping_conf["login"]["email"];
  var password = scraping_conf["login"]["password"];
  if (!login && email && password) {
    document.getElementById("email").value = email;
    document.getElementById("password").value = password;
    ipcRenderer.send("sql-login", email, password, "scraping");
  }
});

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
  ipcRenderer.send("open-file-scraper");
});

// URLリストCSVを選択
const selectUrlList = document.getElementById("select-url-lists");
selectUrlList.addEventListener("click", (event) => {
  ipcRenderer.send("open-file", "selected-url-lists");
});
ipcRenderer.on("selected-url-lists", (event, path) => {
  document.getElementById("url_lists").value = path;
});

// 過去URLリストCSVを選択
const selectOldUrlList = document.getElementById("select-old-url-lists");
selectOldUrlList.addEventListener("click", (event) => {
  ipcRenderer.send("open-file", "selected-old-url-lists");
});
ipcRenderer.on("selected-old-url-lists", (event, path) => {
  document.getElementById("old_url_lists").value = path;
});

// 選択したディレクトリを表示
ipcRenderer.on("selected-directory", (event, path) => {
  document.getElementById("data_dir").value = path;
});

// SQL認証
const SqlLoginBtn = document.getElementById("sql-login");
SqlLoginBtn.addEventListener("submit", (event) => {
  var email = document.getElementById("email").value;
  var password = document.getElementById("password").value;
  ipcRenderer.send("sql-login", email, password, "scraping");
});

// login情報を元に画面編集
ipcRenderer.on("load-login-data", (event, arg_json) => {
  // ログイン成功
  login = true;
  arg_json = JSON.parse(arg_json);
  document.getElementById("user_id").innerHTML = arg_json["user_id"];
  document.getElementById("crawl_limit").innerHTML = arg_json["crawl_limit"];

  // ユーザーの登録しているショップ情報を取得して、ドロップダウンをページに反映
  button_list = "<select onchange=load_shop(this)><option value=-1>ショップを選択してください</option>";
  var user_shop_dict = arg_json["user_shop_dict"];
  keys_list = Object.keys(user_shop_dict);
  for (let i = 0; i < keys_list.length; i++) {
    spider_name = keys_list[i];
    shop_name = user_shop_dict[spider_name]["shop"];
    console.log(spider_name, shop_name);
    button_list +=
      "<option value=" + spider_name + ">" + shop_name + "</option>";
  }
  button_list += "</select>";

  // ショップごとのボタン作成 配列の取得
  document.getElementById("shop-list").innerHTML = button_list;
  document.getElementById("sql-login-status").innerHTML =
    '<font color="green">認証しました</font>';
  document.getElementById("start-status").innerHTML =
    '<a id="start-status"><font color="red">ショップが選択されていません</font></a>';
  // ボタンができるのでその分調整
  AutoAdjust();
});

// ショップボタンを押した際にデフォルト値をロード
function load_shop(obj) {
  global.crawler_or_spidercls = obj.options[obj.selectedIndex].value;
  console.log(crawler_or_spidercls);
  // ショップが選択されていない場合はreturn
  if (crawler_or_spidercls == -1) {
    return;
  }
  // spiderのconfデータを取得
  var spider_data = "";
  if (scraping_conf) {
    var spider_data = scraping_conf[crawler_or_spidercls];
  }
  // GUIにconfデータを反映
  if (spider_data) {
    keys_list = Object.keys(spider_data);
    for (let i = 0; i < keys_list.length; i++) {
      let key = keys_list[i];
      try {
        document.getElementById(key).value = spider_data[key];
      } catch (error) {
        console.log(error);
      }
    }
  }

  document.getElementById("start-status").innerHTML =
    '<a id="start-status"><font color="green">設定が完了しました。(' +
    crawler_or_spidercls +
    ")</font></a>";
  checker = true;
}

function start_check() {
  if (!checker) {
    ipcRenderer.send("cause-error", "未設定項目", "ショップを選択してください");
    return false;
  }

  // 必須項目
  must_list = [
    "csv_prm",
    "buyplace",
    "sendplace"
  ];
  for (var i = 0; i < must_list.length; i++) {
    if (document.getElementById(must_list[i]).value == "") {
      ipcRenderer.send(
        "cause-error",
        "未設定項目",
        txt1[must_list[i]] + "を入力してください"
      );
      return false;
    }
  }

  // csv_prmの形式チェック
  if (!/^[A-Za-z0-9_]+$/.test(document.getElementById("csv_prm").value)) {
    ipcRenderer.send(
      "cause-error",
      "入力エラー",
      "CSVパラメータは半角英数字プラス、アンダーバー（_）のみで入力してください"
    );
    return false;
  }

  // どちらか必須
  if (
    document.getElementById("start_urls").value == "" &&
    document.getElementById("url_lists").value == ""
  ) {
    ipcRenderer.send(
      "cause-error",
      "未設定項目",
      "開始URLまたはURLリストを入力してください"
    );
    return false;
  }

  // csvのpathチェック
  csv_path_list = [
    "url_lists",
    "old_url_lists",
  ];
  for (var i = 0; i < csv_path_list.length; i++) {
    let data_value = document.getElementById(csv_path_list[i]).value;
    if (data_value.indexOf("https:") !== -1 && data_value !== "") {
      ipcRenderer.send(
        "cause-error",
        "入力エラー",
        txt1[csv_path_list[i]] + "の選択形式が正しくありません。\nファイルを開くで選択してください。"
      );
      return false;
    }
  }

  // 数値リスト
  integer_list = [
    "delivery_price",
    "max_price",
    "vatoff_late",
    "vip_late",
    "duty",
    "deadline",
    "stock",
    "max_page",
    "profit_late",
  ];
  for (var i = 0; i < integer_list.length; i++) {
    let data_value = document.getElementById(integer_list[i]).value;
    if (!/^[-]?([1-9]\d*|0)(\.\d+)?$/.test(data_value) && data_value !== "") {
      ipcRenderer.send(
        "cause-error",
        "入力エラー",
        txt1[integer_list[i]] + "の入力に数値以外の文字が有ります"
      );
      return false;
    }
  }

  // コロンチェック
  colon_list = [
    "buyplace",
    "sendplace"
  ]
  for (var i = 0; i < colon_list.length; i++) {
    let data_value = document.getElementById(colon_list[i]).value;
    let colon = data_value.match(new RegExp(":", "g"));
    if(colon){
      if (colon.length !== 3) {
        ipcRenderer.send(
          "cause-error",
          "入力エラー",
          txt1[colon_list[i]] + "にはコロン「:」が3つ必要です"
        );
        return false;
      }
    } else {
      ipcRenderer.send(
        "cause-error",
        "入力エラー",
        txt1[colon_list[i]] + "にはコロン「:」が3つ必要です"
      );
      return false;
    }
  }

  // 全てOK
  return true;
}

// スクレイピング開始
const StartBtn = document.getElementById("start-scrapy");
StartBtn.addEventListener("click", (event) => {
  // 入力チェック
  if (!start_check()) {
    return;
  }

  // crawler_or_spiderclsはpipelineでなくなってしまう
  var args_list = {
    crawler_or_spidercls: crawler_or_spidercls,
    user_id: document.getElementById("user_id").innerHTML,
    crawl_limit: document.getElementById("crawl_limit").innerHTML,
    data_dir: document.getElementById("data_dir").value,
    url_lists: document.getElementById("url_lists").value,
    old_url_lists: document.getElementById("old_url_lists").value,
    start_urls: document.getElementById("start_urls").value,
    email: document.getElementById("email").value,
    password: document.getElementById("password").value,
  };

  // edit_nameからは既に同じ名前でDBから取得できているので、キーを使い回して取得します
  var keys_list = process.env.scraper_conf_list.split(",");
  console.log(keys_list);
  for (let i = 0; i < keys_list.length; i++) {
    try {
      args_list[keys_list[i]] = document.getElementById(keys_list[i]).value;
    } catch (error) {
      console.log(error);
    }
  }
  ipcRenderer.send(
    "show-info",
    "スクレイピング開始",
    "商品リストの取得を開始しました",
    "アプリを閉じると取得を終了します。\n取得可能商品数はこちらです：" +
      args_list["crawl_limit"] +
      "\n取得ショップ：" +
      args_list["crawler_or_spidercls"]
  );
  ipcRenderer.send("start-scrapy", JSON.stringify(args_list));
});

// ログ画面
ipcRenderer.on("log-create", (event, log_text) => {
  document.getElementById("logs").innerHTML +=
    "<p>[log]: " + String(log_text) + "</p>";
  document.getElementById("footer").scrollTop = document.getElementById(
    "footer"
  ).scrollHeight;
});

// 最後に動的にパッディングする
function AutoAdjust() {
  var padding = document.getElementsByClassName("shop-setting")[0];
  padding.style.paddingTop = document.getElementsByTagName(
    "header"
  )[0].offsetHeight;
  padding.style.paddingBottom = document.getElementsByTagName(
    "footer"
  )[0].offsetHeight;
}

// ヘルプ項目
var txt1 = {
  open_dir: "dataフォルダ",
  max_page: "MAX取得ページ数",
  start_urls: "開始URL",
  url_lists: "商品リストCSV",
  old_url_lists: "過去取得URLリストCSV",
  csv_prm: "CSVパラメータ",
  sex: "性別",
  nobrand: "ノーブランドの取得有無",
  nocategory: "カテゴリ無しの取得有無",
  translate_name: "商品名翻訳",
  no_ban_brand: "禁止ブランド解除",
  edit_name: "商品名の装飾",
  max_price: "最低価格",
  vatoff_late: "VatOff率",
  vip_late: "VIP割引率",
  delivery_price: "送料",
  profit_late: "利益率",
  duty: "関税率",
  duty_pattern: "関税",
  size_variation: "サイズバリエーション",
  buyplace: "買付地",
  sendplace: "発送地",
  buyma_shop: "買付ショップ名",
  tag: "タグ",
  thema: "テーマ",
  season: "シーズン",
  delivery: "配送方法",
  deadline: "購入期限",
  stock: "在庫数",
  memo: "メモ",
  switch: "処理の変更",
};

var txt2 = {
  open_dir: "dataフォルダを選択してください。(/Users/****/Desktop/BUYMA/data)",
  max_page:
    "開始URLから何ページ分商品を取得するかをここで制限することができます。\n0にした場合、最後のページまで取得します。",
  start_urls:
    "ショップの商品一覧ページで、取得を開始したい最初のページURLです。",
  url_lists:
    "取得したい商品のurl_listを記載したCSVファイルを指定することで、指定のURLのみ取得することが可能です。\n設定した場合は開始URLよりも優先されます。",
  old_url_lists: "過去に取得した商品のurl_listを記載したCSVファイルを指定することで、その商品をスキップして取得を進めます。",
  csv_prm:
    "取得した商品がCSVで出力されるので、その際にわかりやすいようにここで名前をつけることができます。\n例えば「farfetch」というショップで「2020/02/28」に取得した場合、こちらの項目に「shoes」と入力すると、「farfetch_shoes_20200228.csv」というCSVファイルが出力されます。",
  sex: "BUYMAに出品する際の性別",
  nobrand: "ノーブランド商品を「ON」にすると取得できるようになります。",
  nocategory: "カテゴリ無しの商品を「ON」にすると取得できるようになります。",
  translate_name: "商品名翻訳を「ON」にすると商品名をgoogle翻訳して取得できるようになります。",
  no_ban_brand:
    "通常Monclerなどは出品禁止になっていますが、許可をもらうと出品できるようになります。\n標準ではMonclerは取得をスキップするので、解除したい場合はこちらで選択してください。",
  edit_name:
    "商品名の先頭に装飾したい文字を入力してください。\n例えば「gucci shoes」という商品の場合、「関税込み◆」と装飾文章を設定すると、「関税込み◆gucci shoes」という商品名になります。",
  max_price:
    "価格計算後の価格が設定した価格以下の場合はスキップされます。\n30000円以下の商品は取得したくない場合は「30000」と数字のみで入力してください。",
  vatoff_late:
    "VatOffがある場合はこちらでパーセンテージを百分率で記入していただくと、価格計算に反映されます。\n%は記入せずに半角数字のみ入力してください。",
  vip_late:
    "VIP割引率がある場合はこちらでパーセンテージを百分率で記入していただくと、価格計算に反映されます。\n%は記入せずに半角数字のみ入力してください。",
  delivery_price:
    "送料は「海外送料」「国内送料」「外注手数料」など、足し算で計算する価格をこちらに合計して入力していただくと正確に価格計算されます。",
  profit_late:
    "利益率のパーセンテージを百分率で記入していただくと、BUYMA手数料なども正確に計算された状態での利益率に合わせた価格設定ができます。\n全ての経費に対する利益率なので、BUYMA手数料など込みで10000円経費をかける場合で、20%に設定をすると、出品価格は12000円になります。\n%は記入せずに半角数字のみ入力してください。",
  duty:
    "関税率がある場合はこちらでパーセンテージを百分率で記入していただくと、価格計算に反映されます。\n%は記入せずに半角数字のみ入力してください。",
  duty_pattern:
    "「関税元払い」「購入者申請時、全額負担」の場合は出品する際に、選択した関税パターンが反映されます。\n「お客様負担」を選択すると、発送地を海外の時に関税の選択をスキップします。",
  size_variation:
    "サイズバリエーションがある場合はこちらを「サイズバリエーションあり」に選択すると、出品時にサイズ展開も反映されます。\n「サイズバリエーションなし」に選択すると、サイズに関する情報はサイズ補足に記入されます。",
  buyplace:
    "BUYMAに出品する際の買付地をBUYMAの表示に合わせて設定してください。\n出品画面を見ると分かる通り、最初「国内」または「海外」を選択します。それぞれの場合で次に続くパターンが違います。\n考え方として、基本「:」で区切るのですが、「:」は3つ用意してください→「:::」\nそこに左から順にBUYMAの出品画面をみながら、自分が買付地に設定したい地域を設定していきます。\n例えば、「海外」「ヨーロッパ」「イタリア」「選択なし」の場合は→「海外:ヨーロッパ:イタリア:選択なし」と記入します。",
  sendplace:
    "BUYMAに出品する際の発送地をBUYMAの表示に合わせて設定してください。\n出品画面を見ると分かる通り、最初「国内」または「海外」を選択します。それぞれの場合で次に続くパターンが違います。\n考え方として、基本「:」で区切るのですが、「:」は3つ用意してください→「:::」\nそこに左から順にBUYMAの出品画面をみながら、自分が買付地に設定したい地域を設定していきます。\n例えば、「国内」「福岡」の場合は→「国内:福岡::」と記入します。",
  buyma_shop: "BUYMAに出品する際の買付先ショップ名に記入する文章を設定します。",
  tag:
    "BUYMAにあるタグの名前を正確に記入してください。\n複数ある場合は「,」で区切ります。\nカテゴリーによってタグが変わりますが、存在しないタグを設定しても自動的にスキップするようにしています。\nしかし、ない場合は1つにつき10秒のタイムラグが生まれてしまうので、ご了承ください。",
  thema:
    "BUYMAにあるテーマを正確に記入してください。\nテーマは一つしか設定できません。",
  season:
    "BUYMAにあるシーズンを選択してください。\nない場合は設定しなくても大丈夫です。",
  delivery:
    "配送方法名を正確に記入してください。\n補足情報の部分はカンマ「,」で区切って入力してください。\n複数の配送方法を選択する場合はコロン「;」で区切って入力してください。",
  deadline:
    "現在の日付から何日後を出品期限にするかを設定します。\n30日間出品したい場合は30と記入します。",
  stock: "BUYMAに出品する際の在庫数を設定します。",
  memo: "出品メモに記入したい内容をこちらに記入してください。",
  switch:
    "こちらは要望があった方にオプションで機能を追加しています。\n通常は空欄で大丈夫です。",
};
// ヘルプボタン
function gethelp(key) {
  console.log(key);
  ipcRenderer.send("show-info", "ヘルプ", txt1[key], txt2[key]);
}

AutoAdjust();

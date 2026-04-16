# PLUSELECT_TOOL 分析サマリ

このドキュメントは、過去に実運用されていた BUYMA 自動出品ツール `PLUSELECT_TOOL.app` の分析結果をまとめたものです。
現在構築中の `buyma_automation` プロジェクトの設計・実装の参考資料として活用してください。

---

## 1. PLUSELECT_TOOL とは

- **作成時期**：2021年3月
- **技術スタック**：Electron（UI）+ Python（Scrapy / Selenium で実処理）
- **OS**：macOS（darwin-x64）向けビルド
- **パッケージ形式**：`.app`
- **識別子**：`com.electron.pluselecttool`
- **現ユーザーの過去利用**：あり（昔このツールで自動出品していた）

## 2. 機能構成（4画面）

PLUSELECT は以下4つの機能を1つのアプリに統合していました。

1. **自動出品ツール（exhibition）**：CSV を読み込んで BUYMA に商品を自動出品
2. **BuyManager**：出品後の商品管理・アクセス/ほしいもの/カート集計・価格調整
3. **商品リスト自動作成ツール（scraper）**：海外ECサイトから商品情報を収集して CSV 化
4. **自動画像加工ツール（imager）**：商品画像にロゴ・背景・透過・フレーム処理を一括適用

## 3. 対応サイト（116 サイト）

主要なサイトだけ抜粋：

- **ハイブランド公式**：gucci, chanel, dior, louisvuitton, prada, balenciaga, celine, fendi, ysl, valentino, burberry, givenchy, loewe, bottegaveneta, versace, tiffany, cartier, swarovski
- **セレクトショップ**：farfetch, mytheresa, netaporter, mrporter, ssense, italist, cettire, yoox, theoutnet, selfridges, saksfifthavenue, harveynichols
- **その他ブランド系**：baseblu, asos, zara, ralphlauren_jp, lacoste, moncler, maxmara, stellamccartney, viviennewestwood

全リストは `docs/reference/pluselect_source/supported_sites.txt` を参照。

## 4. 何が参考になるか（★重要）

### ★★★ 最重要の成果物（そのまま流用推奨）

- **BUYMA 取り込み用 CSV の34列仕様** → `docs/reference/CSV_COLUMNS.md`
  - この列定義は BUYMA 側の期待フォーマットに合致していた実績あり
  - `buyma_automation` の CSV 出力モジュールの設計にそのまま使える
- **設定項目リスト（.env から抽出）** → `docs/reference/CONFIG_PARAMETERS.md`
  - スクレイパー・画像加工・出品・管理それぞれで必要なパラメータが網羅されている
  - `config.json` の設計に流用可能

### ★★ 読める参考資料（設計のヒント）

- **UI 画面の HTML**（`pluselect_source/src/public/*.html`）
  - 実業務で使っていた入力項目が全て揃っている
  - 将来 Web UI を作るときの項目リストの叩き台
- **JavaScript のフロー制御コード**（`pluselect_source/src/components/*.js`, `views/*.js`）
  - 重複チェック、CSV読み込み、ログイン、出品開始などの**処理の流れ**が読める
  - 具体的な Python の中身は読めないが、「何をどの順に呼んでいるか」は参考になる

### ★ その他の参考資料

- **Python パッケージ一覧**（`packages.yml`, `python_modules.yml`）
  - Scrapy, Selenium, Pillow, OpenCV, jaconv（日本語変換）, pymysql などを使っていた
  - `buyma_automation/requirements.txt` の検証時に参考にする

## 5. 参考にならない部分（読めない）

以下は **PyArmor で暗号化されている**ため、処理内容の解析は不可能です：

- `scraping/items.py`, `middlewares.py`, `models.py`, `pipelines.py`, `settings.py`, `tool.py`
- `scraping/spiders/*.py`（116 サイトのスクレイパー全部）
- `python_scripts/exhibition.py`, `BuyManager.py`, `imager.py`, `login.py`, `stock_check.py`, `stock_reflect.py`, `base.py`, `python_tools.py`, `scrapy_start.py`

**含意**：各サイトの個別スクレイピングロジック、BUYMA 出品時の細かい手順、画像加工のアルゴリズム、在庫同期の実装は、ゼロから書き起こす必要があります。

## 6. 設計・運用面の学び

PLUSELECT の設計から読み取れる「業務運用上の工夫」：

1. **重複チェックは必須機能**：`duplicate` 設定項目あり。BUYMA の重複出品ペナルティを避けるため
2. **下書き出品モードの存在**：`draft` 設定項目あり。いきなり公開せず下書きで検証する運用
3. **出品間隔のランダム化**：`wait_time` 設定項目あり。BOT検知回避のため
4. **VAT還付・VIP割引の計算**：欧州サイトからの仕入は VAT 還付でコスト圧縮できる（約16.7%）
5. **画像加工の設定項目が非常に多い**：商品画像の差別化が売上に直結していた証拠
6. **BuyManager 機能の存在**：出品して終わりではなく、アクセス数・ほしいもの登録数を見て価格調整する運用が重要

## 7. `buyma_automation` への反映方針

- **即流用**：CSV 34列フォーマット、設定項目リスト
- **設計参考**：UI項目リスト、処理フロー（各モジュールの呼び出し順）
- **要再実装**：スクレイピングロジック全般、BUYMA 出品実装、画像加工、在庫同期
- **運用で真似する**：重複チェック、下書き出品、出品間隔ランダム化、VAT還付計算

## 8. ファイル配置

```
docs/reference/
├── PLUSELECT_ANALYSIS.md      ← このファイル（サマリ）
├── CSV_COLUMNS.md             ← 34列仕様
├── CONFIG_PARAMETERS.md       ← 設定項目一覧
└── pluselect_source/          ← 原本ファイル（読めるもののみ）
    ├── csv_columns_raw.txt
    ├── env_config_raw.txt
    ├── package.json
    ├── packages.yml
    ├── python_modules.yml
    ├── scrapy.cfg
    ├── supported_sites.txt
    └── src/
        ├── main.js
        ├── components/*.js
        ├── views/*.js
        └── public/*.html
```

## 9. 元フォルダへの参照パス

Claude Code が直接原本フォルダにアクセスする必要があるとき：

```
/Users/mgakusei/Downloads/PLUSELECT_TOOL-darwin-x64 2/PLUSELECT_TOOL.app/Contents/Resources/app/
```

ただし基本的には `docs/reference/` にコピー済みの抜粋で事足ります。
原本フォルダには暗号化された Python コードが大量にあり、アクセスしても解析できません。

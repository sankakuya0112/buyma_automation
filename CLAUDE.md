# CLAUDE.md - プロジェクト指示書

このファイルは Claude Code がセッション開始時に読み込む指示書です。
過去の経験から得た知見を記録し、同じミスを繰り返さないようにします。

---

## プロジェクト概要

BUYMA 自動出品ツール。baseblu.com からセール商品をスクレイピングし、
価格計算・翻訳を経て BUYMA に自動出品するパイプライン。

**メインスクリプト**: `scripts/buyma_auto_listing.py`  
**ブランチ**: `claude/add-test-flag-HibqE`

---

## 🔑 BUYMA 出品フォームの仕様（Playwright 自動操作の知見）

BUYMA の出品フォーム (`/my/sell/new?tab=b`) を自動操作する際の
**罠と対策**を以下に記録する。同じミスを繰り返さないこと。

### 1. 遅延描画 (lazy render) を使っている

BUYMA のフォームは **画面外の要素を DOM にすら存在させない**。
スクロールして近づいたときに初めて React が生成する。

**対策**: `_scroll_through_page(page)` ヘルパーを呼んでからクエリする。
12回 × 500px のホイールスクロールで全セクションを render させる。
`page.mouse.wheel()` でユーザー操作を再現するのが効果的（JS の `window.scrollTo`
だけだと IntersectionObserver が発火しないことがある）。

### 2. 条件付きレンダリング（ブランド入力 → 品番出現）

**ブランドを正しく選択すると初めて「品番/識別メモ」セクションが DOM に出現する。**
ブランド未入力の状態ではスクロールしても品番 input は存在しない。

**対策**: `process_product()` の処理順序を
`… → set_purchase_memo → select_brand → set_sku → save_draft` に固定する。
`set_sku` は必ず `select_brand` の後に呼ぶ。

### 3. react-select の選択は DOM クリック必須

`window.__srs()` で React の onChange prop を直接呼び出す方式は、
BUYMA の内部 state を完全には更新しないケースがある。例:
- ブランド: 「BUYMAに登録されていないブランド名」警告が残り保存拒否
- 色/サイズ: 表示は変わるが保存時に無効扱い

**対策**: `_click_select_option()` を使い、`mousedown` イベント dispatch または
Playwright の `locator.click()` で**本物のマウスクリック**を再現する。

### 4. サジェスト候補も DOM クリック必須

ブランド input に文字を入れて現れるサジェスト候補 `.bmm-c-suggest__option--selectable`
も同じく Playwright の `locator.click()` が必須。React onClick prop 直叩きでは
状態が完全反映されない。`select_brand()` 参照。

### 5. BUYMA のブランド API は移行済み

旧: `https://www.buyma.com/rorapi/suggest/brands.json`（404）
新: `https://cdn-suggest.buyma.com/brand_suggest?keyword=XXX`

Response 形式: `[{"text": "GIVENCHY", "phonetic": "ジバンシィ", "brand_id": 43}]`

画像アップロード API は依然 `/rorapi/item_image.json` で生きている
（POST = upload、DELETE = 削除）。

### 6. 画像アップロードは `page.expect_response()`

`page.on("response", ...)` だと初回レスポンスを見逃してリトライが走り、
**同じ画像が 2 回以上アップロード**される不具合が発生する。
`page.expect_response(POST item_image.json)` で待機する方式が正解。

### 7. 商品コメントのアクセント文字は validation エラー

"Lavallière" など Latin アクセント付き文字が含まれると
「商品コメントに不正な文字『è』が含まれています」で弾かれる。
`_strip_accents()` で NFD 分解 + combining mark 除去を必ず適用する。

### 8. タブパネル ID は固定ではない

`#react-tabs-1` `#react-tabs-3` のような ID は BUYMA 側でバージョンによって変わる。
`_click_tab_by_name(page, "色")` で `aria-controls` 属性から動的に panel id を
取得すること。

### 9. DOM 位置ベースのセクション内要素探索

出品メモ と 買付先メモ の両 textarea は**共通祖先に両方のタイトル文字列を含む**ため、
ancestor 探索だと誤って 1 つの textarea に両方書き込まれる。
`_fill_in_section(section_title, value, tag, input_idx)` で、
見出しの DOM 位置と次見出しの DOM 位置の**範囲内**で N番目の要素を選ぶ方式が正しい。

### 10. 品番フィールドの特定方法

`.sell-model-number-table` クラス配下の 1つ目 input が品番、2つ目が識別メモ。
placeholder には SKU サンプル（例 `1BD075_2BLF_F0002_V_KOO`）が入っており、
正規表現 `^[A-Z0-9][A-Z0-9_\-]{5,}$` で一意に特定できる（上述の条件付き
レンダリングで DOM に出現してから）。

### 11. ブランドは保存直前に設定

他 setter の React 再レンダリングで brand state がリセットされる。
`select_brand()` は `process_product()` の末尾 (save_draft 直前の、
set_sku の直前) に配置する。

### 12. 発送地・買付地は 2段セレクト

- 買付地: 大陸 dropdown → 国 dropdown（例: ヨーロッパ → イタリア）
- 発送地: 国内/海外 radio → 都道府県 dropdown（例: 国内 → 神奈川県）

`set_region()` で `_find_section_selects()` を使いセクション内の Select を取得。

### 13. 下書き保存ボタンは Playwright クリック必須

JS の `button.click()` では React ボタンが反応しないケース多数。
`page.locator('button:has-text("下書き保存する")').click()` を使う。

### 14. CSV パイプラインから渡るデータ構造

```
baseblu_sales_to_csv.py → filter_baseblu_profitable.py → buyma_auto_listing.py
```

- **SKU**: variant SKU から末尾 `_<option1 値>` を剥がして製品レベルに正規化。
  `description_en` に "Sku: XXX" と明記されている場合はそちらを優先
- **color**: JSON options / variants.option2 / tags / body_html / title keyword /
  **商品ページ HTML から抽出**（5+1段フォールバック）
- **sizes**: `variants[].option1` から全バリアント取得（カンマ区切り）
- **season**: `description_en` の "Season: AW25" 正規表現
- **product_type**: Shopify の `product_type`。BUYMA カテゴリ 3階層マッピングの入口
- **日本語翻訳**: DEEPL_API_KEY 設定時は DeepL 経由、無ければ FASHION_TERMS 辞書置換

### 15. brands.json のスキーマ

```json
{
  "brands": {"gucci": {"brand_id": 203, "phonetic": "グッチ"}},
  "unregistered": ["..."],
  "auto_lookup_enabled": true
}
```

brand_id が `null` なら出品時に CDN API で自動取得して上書き保存する。
手動追加時は brand_id を明示指定するか、一度実行すれば自動補完される。

### 16. categories.json のスキーマ

```json
{
  "default": ["レディースファッション", "小物", "その他"],
  "mappings": [
    {"product_type": "BAGS", "default": [...], "keywords": [
      {"match": ["shoulder bag"], "path": ["レディースファッション", "バッグ・カバン", "ショルダーバッグ"]}
    ]}
  ]
}
```

title 中のキーワードで 3階層パス（parent > middle > leaf）を決定。
キーワードにマッチしなければ product_type の default、それもなければ
グローバル default を使う。

---

## 実行環境について（重要）

### Claude Code サーバーでできること ✅
- コードの編集・作成
- DB 操作（SQLite）
- パッケージインストール（pip）
- ロジックのテスト（モックデータ使用）
- GitHub へのコミット・プッシュ

### Claude Code サーバーでできないこと ❌
- `baseblu.com` へのアクセス（ホワイトリスト外）
- `buyma.com` / `buyma.jp` へのアクセス（ホワイトリスト外）
- playwright のブラウザダウンロード（CDN がブロック）
- 一般的な外部 Web サイトへのスクレイピング

**理由**: Anthropic がセキュリティ上の理由で設けたネットワーク制限。
`GLOBAL_AGENT_HTTP_PROXY` に許可ドメインのホワイトリストが設定されている。
pypi.org・github.com 等の開発インフラのみ許可されている。

### 実際のスクレイピング・出品は Mac（ローカル）で実行する

```bash
cd ~/buyma_automation
git pull origin claude/add-test-flag-HibqE
pip3 install -r requirements.txt
pip3 install playwright && playwright install chromium
python3 scripts/run_pipeline.py --test
```

---

## 失敗パターンと対策

### ❌ 失敗1: Claude Code サーバーから外部サイトにアクセスしようとした
- **発生**: `python3 scripts/run_pipeline.py --test` を実行 → baseblu.com に接続できず失敗
- **エラー**: `ProxyError: Tunnel connection failed: 403 Forbidden`
- **原因**: Claude Code サーバーのネットワーク制限
- **対策**: スクレイピング・出品はユーザーの Mac で実行するよう案内する。サーバーで実行しない

### ❌ 失敗2: playwright のブラウザダウンロードが失敗した
- **発生**: `playwright install chromium` → CDN から 403 エラー
- **原因**: playwright の CDN もホワイトリスト外
- **対策**: サーバー上にある既存の Chromium を使用する
  - パス: `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`
  - `p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")`
  - `config.chromium_executable_path` で管理している

### ❌ 失敗3: Mac から GitHub へ push しようとしてパスワード認証を求められた
- **発生**: `git push` → GitHub ユーザー名・パスワードを求められた
- **原因**: GitHub はパスワード認証を廃止（Personal Access Token が必要）
- **対策**: Mac から push は不要。Claude Code サーバー側で push する。
  ユーザーには push を求めず、ファイル内容をチャットに貼り付けてもらう

### ❌ 失敗4: Mac に存在しないファイルを cp しようとした
- **発生**: `cp .env.example .env` → `No such file or directory`
- **原因**: `.env.example` はサーバー側にあるが Mac には同期されていなかった
- **対策**: Mac にないファイルを前提とした手順を案内しない。
  代わりに `cat > .env << 'EOF'` で直接作成する手順を案内する

### ❌ 失敗5: docs/ ファイルが Mac にあってサーバーにない状態を把握できなかった
- **発生**: `docs/phases/PHASE1_FOUNDATION.md` を読もうとしたが見つからなかった
- **原因**: ファイルが Mac ローカルにあり、GitHub に push されていなかった
- **対策**: ファイルが見つからない場合、すぐに「GitHub にプッシュするか内容を貼り付けてください」と案内する

### ❌ 失敗6: セキュリティ上問題のある情報をチャットで共有してもらった
- **発生**: BUYMA のログイン情報（メール・パスワード）をチャットに貼り付けてもらった
- **原因**: サーバー側に `.env` を設定する手段として誘導してしまった
- **対策**: 認証情報はユーザーの Mac 上で `.env` や `config.json` に設定するよう案内する。
  チャットへの貼り付けは避けてもらう（低リスクであっても）

---

## 成功パターン

### ✅ 成功1: モックデータを使ったパイプラインテスト
- `python3 scripts/run_all.py --test` → 正常動作
- モックデータ3件で価格計算・翻訳・CSV保存まで完走

### ✅ 成功2: SQLAlchemy DB の初期化・モデル定義
- `app/core/models.py` の8テーブル定義が正常動作
- `init_db()` で SQLite DB を初期化できることを確認済み

### ✅ 成功3: 全モジュールのインポート確認
- `app/` 以下の全モジュールが正常にインポートできることを確認済み

### ✅ 成功4: 既存 Chromium を使った Playwright 起動
- `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` で Playwright が動作することを確認
- `executable_path` を `config.chromium_executable_path` で管理

### ✅ 成功5: ファイル内容をチャットに貼り付けてもらう方法
- GitHub push ができない場合でも、ファイル内容をチャットに貼り付けてもらうことで対応できた

---

## 開発フロー

1. コードは Claude Code サーバーで編集・テスト（モックデータ）
2. コミット・プッシュは Claude Code サーバーから実行
3. 実際のスクレイピング・出品テストはユーザーが Mac で実行
4. エラーが出たらターミナルの出力をチャットに貼り付けてもらい、Claude Code で修正

---

## 認証情報の管理

- BUYMA のメール・パスワードは **Mac 上の `.env` または `config.json`** に設定
- `config.json` は `.gitignore` に追加済み（GitHub に漏れない）
- `.env` も `.gitignore` に追加済み
- チャットには絶対に貼り付けない

---

## 参考資料（PLUSELECT_TOOL の分析結果）

過去に実運用されていた BUYMA 自動出品ツール `PLUSELECT_TOOL.app` を分析し、
参考になる部分を `docs/reference/` に抽出・配置済み。新機能の設計・実装時は
まず以下を確認して、既存の知見を活用すること。

### 最初に読むべきファイル

- `docs/reference/PLUSELECT_ANALYSIS.md` … PLUSELECT の全体像と「何が使えて何が使えないか」の要約
- `docs/reference/CSV_COLUMNS.md` … BUYMA 取り込み用 CSV の 34 列仕様（★最重要）
- `docs/reference/CONFIG_PARAMETERS.md` … 運用で必要になる設定項目の網羅リスト

### 原本ファイル群（コピー済み）

- `docs/reference/pluselect_source/` 以下に、読める原本ファイル（HTML/JS/設定ファイル）をコピー済み
- PLUSELECT の UI 設計や処理フローを確認したいときはここを参照

### 原本フォルダ（全量アクセスが必要な場合のみ）

- パス：`/Users/mgakusei/Downloads/PLUSELECT_TOOL-darwin-x64 2/PLUSELECT_TOOL.app/Contents/Resources/app/`
- **注意**：Python コード（`python_scripts/*.py`, `scraping/*.py`, `scraping/spiders/*.py`）は
  PyArmor で暗号化されており解析不能。読み込みに時間を浪費しないこと
- 基本的には `docs/reference/` に抽出済みの情報で事足りる

### PLUSELECT を参考にする際のルール

1. まず `docs/reference/PLUSELECT_ANALYSIS.md` を読み、全体像を把握してから原本に当たる
2. 暗号化された Python ファイル（PyArmor 署名で始まるファイル）は開かない
3. CSV フォーマット・設定項目は PLUSELECT のものをベースに使い、BUYMA 側の最新仕様と差分があれば要修正
4. UI/処理フローは参考にするが、**具体的な実装は `buyma_automation` で新規に書く**
   （PLUSELECT の JS/HTML コードをコピペしない）

---

## 利益最優先の実装指示書

ルートディレクトリの `PROFIT_FIRST_INSTRUCTIONS.md` に、利益を最優先とした
フェーズ別タスク一覧・実装方針・運用ルールを記載済み。新規実装時はここを参照。

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

## 🚨 開発ルール（必ず守る）

### 実装前に必ず plan モードで設計を出す

コードを 1 行でも書く前に、**plan モード** (ExitPlanMode が必要な設計モード) で
以下を含む設計を提示し、ユーザ承認を得てから実装に入ること:

- Context: なぜその変更が必要か
- 対象ファイルと関数 (file:line 付き)
- 既存の再利用資産 (既に実装済みのものを使い回す)
- 実装タスクの分解
- 検証方法

**理由**:
1. トークン節約 (無駄な往復・作り直しを防ぐ)
2. 設計ミスの早期発見 (書いた後に方針変更すると大きく巻き戻る)
3. 非対象範囲の合意 (スコープ膨張防止)

**例外**: typo 修正 / 1 行 log 追加 / 明確に「〇〇を直して」と即時指示された trivial
修正のみ plan をスキップ可。判断に迷う場合は plan を出す方に倒すこと。

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

**罠 (2026-06-10/16 実走で確定)**: 発送地の都道府県 select は「国内」radio
クリック後に**遅延描画**される。さらに radio 自体に罠がある:
1. **radio は Playwright native click でも React state が更新されない**
   (§3 と同型)。input.checked は true になるが controlled state は海外のまま
   で、都道府県 select が一切 render されない (実測: 全 23 select に神奈川県皆無、
   海外エリア select=ビーチ/リゾート/グアム が残り続ける)
2. 前方一致だと `'国内'` が `'国内海外'` コンテナに誤マッチする
対策: `_click_section_radio` は radio input を**完全一致**で特定して
data 属性タグ付け → **native checked setter で .checked=true を入れ
click/input/change を dispatch して React onChange を強制発火**
(window.__si と同型) → 仕上げに Playwright native click(force) 併用 →
`_radio_checked` で検証。都道府県 select は radio 成功後に出現を最大 6 秒
ポーリング (section scrollIntoView + 実ホイール併用)。
⚠️ 全域 select 走査のフォールバックは**禁止** (2026-06-10 に 62 スキャン ×
179 リトライでページ状態を乱し、買付地まで壊した実績がある)。
なお発送地が未設定でも**下書き保存は通る** (本公開時に必須になる想定)。

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

⚠️ **第2階層 (middle) は BUYMA に実在する正式名でなければ保存 API が
422 (cate_id: 第2カテゴリを選択してください) で弾く** (2026-06-10 実走で確定)。
第3階層 (leaf) は `set_category` の部分一致 / その他 fallback があるため
ある程度ズレても通るが、第2階層は fallback が無いので致命的。
`data/categories.json` の `_tier2_valid` に出品フォームから実採取した
第2階層名 (トップス/ボトムス/ワンピース・オールインワン/アウター/
靴・シューズ/ブーツ/バッグ・カバン/財布・小物/アクセサリー/腕時計/
アイウェア/帽子/ファッション雑貨・小物/...) を保存済み。
`tests/test_categories_schema.py` が全マッピングの第2階層を CI で照合する。
実カテゴリツリーの再採取は `scripts/harvest_buyma_categories.py` (Mac 専用)。
**未採取の第3階層**: ブーツ配下 / 帽子配下 / トップス配下 / アクセサリー配下
/ アイウェア配下 (leaf は推定値。必要なら harvest スクリプトで追加採取)。

---

## 🗂 プロジェクト構造の重要な置き場 (Phase 2c+ 以降)

新規実装やテスト追加時、まず以下の既存資産を確認して再利用すること。
似た実装を別場所に作らないこと。

### 純粋関数 (Playwright 非依存) は `app/utils/listing_helpers.py`
- `_strip_accents(text)` — 日本語濁点を保ったまま Latin アクセント除去
- `map_size_to_jp_reference(size, product_type)` — IT サイズ → BUYMA 参考日本サイズ
- `_map_footwear_to_jp_cm(size)` — EU/IT 数値 → cm ラベル (女性靴 34〜41.5)
- `translate_color_to_jp(color)` — 英語色 → BUYMA 系統ラベル
- `normalize_size_for_buyma`, `classify_size_category`, `format_size_name_for_listing`
- 定数: `COLOR_JA_MAP`, `_IT_SIZE_RANGES`, `_ALPHA_SIZE_TO_JP`, `_EU_SHOE_TO_JP_CM`

`scripts/buyma_auto_listing.py` からはこれを import している。**新たに純粋な
変換関数を書くときは scripts/ ではなく app/utils/ に配置**して `tests/test_listing_pure_functions.py`
にテストを追加すること。

### 仕入先 (Source) の抽象化は `app/core/sources/`
- `BaseSource` ABC: `name` / `currency` / `country` / `landed_cost_basis` / `get_pricing_params()`
- `BasebluSource`: name=baseblu / currency=EUR / country=IT / landed_cost_basis=DDU
- `get_source(name)` factory: 未登録は baseblu に fallback (旧 CSV 透過処理)

**新仕入先の追加は原則コード不要** (2026-09-11):
`data/sources.json` に 1 ブロック足すだけで `ConfigSource` として解決される。

```bash
python3 scripts/shopify_sales_to_csv.py --list                    # 設定済み一覧
python3 scripts/shopify_sales_to_csv.py --source <名前> --probe   # 取得可否の確認 (Mac)
python3 scripts/shopify_sales_to_csv.py --source <名前>           # CSV 生成
python3 scripts/filter_baseblu_profitable.py --source <名前>      # 利益計算
python3 scripts/run_autopilot.py --source <名前>                  # 全工程
```

- `get_source(name)` の解決順は **専用クラス → data/sources.json → baseblu fallback**
- 設定が壊れていれば `ValueError` で止める (誤った原価で出品するより止める)
- 未検証の仕入先は `status: "unverified"` + `landed_cost_basis: "DDU"` +
  `vat_refund_rate: 0.0` (原価を高く見積もる安全側)。`tests/test_sources_config.py` が強制する
- baseblu / italist のように専用クラスもある仕入先は、両方の値が一致していることを
  テストが照合する (二重管理による VAT 二重控除事故の防止)

サイト固有の処理 (商品ページ HTML の解析等) が要る場合だけ専用クラスを書く:
1. `app/core/sources/<name>.py` に `class <Name>Source(BaseSource)` を作る
2. `app/core/sources/__init__.py:REGISTERED_SOURCES` に登録
3. `tests/test_sources.py` にメタデータ検証テストを追加
4. `data/categories.json` / `brands.json` に必要なら拡張

⚠️ **baseblu は専用の `scripts/baseblu_sales_to_csv.py` を使い続ける**
(商品ページ HTML からの色抽出があり、汎用版は JSON のみ扱うため)。

CSV 列に `source_name` / `currency` / `landed_cost_basis` を出力する規約。
`scripts/filter_baseblu_profitable.py` は `get_source(row.get('source_name'))` で
動的解決するため、ハードコードを増やさないこと。

### 期待値スコア (商品選別) は `app/core/opportunity.py` (Phase 2d)
- `opportunity_score = expected_profit_jpy × P(成約)`
- `DemandSignals` dataclass: market_sample_count / source sellthrough /
  discount_rate / market_wish_total
- `estimate_sale_probability(competition_level, price_edge_ratio, signals)`
- filter の CSV ソートはこの期待値順。係数は成約実績で較正する前提
- 戦略の全体像: `docs/strategy/DEMAND_DISCOVERY.md`

### 需要起点スカウトは `scripts/scout_demand.py` (Phase 2d)
- モード1 (オフライン): market_cache → ブランド需要インデックス
  (data/demand_index.json)
- モード2: `--match-source latest` で需要×供給の交点
- モード3 (Mac): `--probe-from-csv latest` でブランド需要を能動調査
- 価格決定の `price_leader` / `market_aware_discounted` 経路とセットで
  「需要実証済み商品を原価優位で出す」戦略を構成する

### 仕入先優位スコア `source_edge` は `app/core/source_edge.py`
- `SourceEdgeStats` dataclass: cheapest / second_cheapest / edge_jpy / edge_pct
- `evaluate_source_edge(edge, final_price, current_source)`:
  4 経路 (exclusive_source / not_cheapest_source / low_source_edge / high_source_edge)

詳細設計は `docs/strategy/SOURCE_EDGE_DESIGN.md`。本格運用は **2 仕入先目** が
必要なため、Italist 実装後に Milestone 2 (data/source_index.json + Levenshtein
マッチング) に進む。

### 市場相場の品質チェックは `scripts/audit_market_cache.py`
`fetch_buyma_market_prices.py` のキャッシュ JSON を走査:
- `python3 scripts/audit_market_cache.py` — 統計 (ok/suspicious/legacy/empty)
- `--re-evaluate` — `raw_items` から `compute_stats` 再計算 (新ロジック適用)
- `--threshold 0.5` — `brand_match_confidence` の閾値変更

旧キャッシュ (legacy = フィールド未存在) はキャッシュ無視で再 fetch が必要。
新キャッシュには `raw_items` が forward 互換で保存される。

### エラー通知は `app/utils/notifier.py`
- `notify(level, title, body)` — Slack + email 両送信
- `notify_error(operation, exc, context=None)` — 例外時の整形通知
- 環境変数: `SLACK_WEBHOOK_URL`, `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`, `NOTIFY_EMAIL_TO`/`NOTIFY_EMAIL_FROM`
- 設定なしなら silent skip (開発環境で誤通知の心配なし)
- `NOTIFY_DRY_RUN=1` で実送信せず stdout 出力

### AI 補助層 (Claude API) は `app/ai/` (2026-09-11)
- `app/ai/router.py`: タスク → 階層 (cheap/standard/premium) → モデル ID の**唯一の割り当て表**。
  cheap=Haiku 4.5 (出品文・カテゴリ) / standard=Sonnet 5 (審査・診断) / premium=Fable 5.1 (週次レビュー)
- `app/ai/client.py`: `AIClient.complete_json / complete_text`。**None を返す = AI なしで続行**。
  SQLite キャッシュ (data/ai_cache.sqlite)・JSONL 台帳 (data/ai_usage.jsonl)・週間予算 (AI_WEEKLY_BUDGET_JPY)
- `app/ai/tasks/`: listing_copy / category / judge / review / diagnose。**新しい AI 用途はここに追加し、
  router.py に TaskPolicy を登録**する。scripts/ に直接 API 呼び出しを書かない
- 入口: `scripts/run_autopilot.py` (全工程) / `scripts/ai_enrich_candidates.py` (補強のみ) /
  `scripts/ai_cost_report.py` / `scripts/ai_diagnose.py`
- 出品スクリプトは CSV の `category_path` / `ai_title_ja` / `ai_description_ja` / `ai_color_ja` / `ai_verdict`
  を優先使用する (`resolve_listing_*`)。`ai_verdict=skip` は出品対象外、`hold` は `--include-review` 時のみ
- ルール: (1) 決定論で決まることに AI を使わない (2) 量のタスクは cheap、判断は standard、
  週 1 の戦略だけ premium (3) system prompt に日付・乱数を入れない (prompt cache が壊れる)
  (4) API キーはチャットに出さない。詳細: `docs/AI_MODEL_POLICY.md`

### テスト実行
```bash
python3 -m unittest discover tests        # 全件 (現状 466 ケース)
python3 -m unittest tests.test_pricing -v  # 個別ファイル
```

CI (.github/workflows/test.yml) で push/PR 時に Python 3.11 + 3.12 マトリクスで
自動実行されるため、commit 前にローカルで全 PASS を必ず確認すること。

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
- `config.json` は 2026-06-09 に git 追跡解除 + `.gitignore` 追加済み
  (それ以前は誤って追跡されていた。履歴に実パスワードが入ったことはない)
- 新環境では `config.json.example` をコピーして `config.json` を作る
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

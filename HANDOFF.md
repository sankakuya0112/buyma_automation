# 引き継ぎノート（2026-06-09 セッション終了時点 / 8回目更新）

---

## 🆕 2026-09-11 追記: AI オートパイロット (モデル使い分け + トークン節約)

ユーザー要望: 「利益が出る商品の仕入れ → 収益計算 → 出品作業」を AI で自動化。
モデルを使い分けてトークンを節約すること。

### 追加したもの
- `app/ai/` — router (割り当て表) / client (キャッシュ・台帳・予算・オフライン退避) /
  tasks (出品文=Haiku、カテゴリ=Haiku 番号回答、審査=Sonnet、診断=Sonnet、週次レビュー=Fable)
- `scripts/run_autopilot.py` — 取得 → 利益 → 相場 → **AI 補強** → (任意) 下書き → 費用レポートを 1 コマンド。
  `--test` でモック通し確認 (サーバーでも動く)、`--draft N`、`--weekly-review`、`--no-ai`
- `scripts/ai_enrich_candidates.py` — filter 済み CSV の上位 N 件に `category_path` / `ai_title_ja` /
  `ai_description_ja` / `ai_keywords` / `ai_color_ja` / `ai_verdict` / `ai_risk_flags` / `ai_reason` /
  `ai_priority` 列を追加 (同じファイルを上書き)。`--dry-run` で費用概算
- `scripts/ai_cost_report.py` / `scripts/ai_diagnose.py`
- `scripts/buyma_auto_listing.py` — AI 列を優先使用 (`resolve_listing_category/title/color`、
  `generate_description(desc_ja=)`)。`ai_verdict=skip` 除外、`hold` は要確認扱い。
  **出品順を AI 優先度 → opportunity_score → 利益額に統一** (旧: 利益順に並べ直していた)
- `docs/AI_MODEL_POLICY.md` — 原則・割り当て・費用目安 (≈¥45/週)・変更方法・制約
- テスト 318 → 392 ケース (AI 層は SDK フェイクでオフライン検証)

### Mac 側で次にやること
1. `.env` に `ANTHROPIC_API_KEY=` を追加 (console.anthropic.com で発行。チャットに貼らない)
2. `pip3 install -r requirements.txt` (anthropic 追加)
3. `python3 scripts/run_autopilot.py --test` → 全工程完了を確認
4. `python3 scripts/ai_enrich_candidates.py --dry-run` → 概算費用を見る
5. `python3 scripts/run_autopilot.py` → 実データで AI 補強。CSV の ai_* 列を目視
6. `python3 scripts/run_autopilot.py --skip-scrape --skip-market --draft 1` → 下書き 1 件で
   AI タイトル/説明/カテゴリが BUYMA フォームに入るか確認 (カテゴリ 422 が出たら
   categories.json の `_tier2_valid` を疑う)

### 未検証 (サーバーからは API に到達できないため)
- 実 API での structured outputs (Haiku 4.5 で `output_config.format` が通るか)。
  通らない場合はクライアントが自動で「JSON のみ出力」指示に切り替える
- Fable 5.1 の `fallbacks="default"` (beta `server-side-fallback-2026-07-01`)。
  400 になる場合は `AI_MODEL_PREMIUM=claude-opus-5` で回避

## 🆕 2026-06-16 追記: 実カテゴリツリー採取 → categories.json 全面修正 + 発送地 React 発火

### カテゴリ 422 の根治 (data 修正)
Mac が `scripts/harvest_buyma_categories.py` で BUYMA 出品フォームの実カテゴリ
ツリーを採取。**categories.json の第2階層が 23 箇所も実在しない名前**
(小物/パンツ/スカート/デニム/ワンピース/シューズ) だったと判明。
第2階層は fallback が無く 422 直撃するため致命的だった。
- `data/categories.json` を実採取した第2階層名 (トップス/ボトムス/...) に全面修正。
  `_tier2_valid` (検証済み第2階層リスト) と `_todo_harvest` (未採取 leaf) を追記
- 50 マッピング全ての第2階層が実在名であることを検証済み
- `tests/test_categories_schema.py` 新規: CI で第2階層を照合 (退行防止)
- ⚠️ **未採取の第3階層** (ブーツ/帽子/トップス/アクセサリー/アイウェア配下) は
  leaf を推定値で埋めた。set_category の その他 fallback で吸収される想定だが、
  これらカテゴリの出品時は要確認。harvest スクリプトで追加採取可
- ⚠️ `scripts/harvest_buyma_categories.py` は **Mac ローカルのみ**。
  Mac 側で commit & push してリポジトリに入れること

### 発送地ラジオの React state 強制発火 (code 修正)
Mac の `[DIAG-発送地]` 全 select インベントリ (23件) で**神奈川県を含む select が
皆無**、掴んでいた [18,19] は海外エリア (ビーチ/リゾート) と海外国 (グアム) と判明。
= 「国内」radio を native click しても React controlled state が海外のままで
都道府県 select が描画されていなかった (CLAUDE.md §3 の罠が radio に該当)。
- `_click_section_radio` を **native checked setter + click/input/change dispatch**
  で React onChange を強制発火する方式に変更 (window.__si と同型) + Playwright
  click(force) 併用。買付地「海外」radio にも同経路が適用される
- **次回 Mac 実走で「発送地=神奈川県」が出るか要検証**。まだ出なければ
  [DIAG-発送地] が再度ダンプするので select 種別を再確認

---

## 🆕 2026-06-10 追記3: 3件連続テストの診断と修正 (radio/カテゴリ/スキャン撤去)

### 3件連続テスト結果 (--from 2 --limit 3)
- #1 ALAÏA → draft 133231659 / #2 SA SU PHI → save_failed (422) /
  #3 ALAINPAUL → draft 133231786。ブランド CDN 自動解決は 3/3 成功
- 発送地はまだ未設定 + 所要 8 分 25 秒 (リトライ 179 回) と不安定化

### 真因と修正 (サーバー側、要 Mac 再検証)
1. **radio の JS click() が React state を更新していなかった** (決定的証拠:
   神奈川県を探した select の中身が海外用エリアリスト = 内部 state が海外のまま。
   '国内' が '国内海外' コンテナに前方一致する問題も併発)
   → `_click_section_radio` を data 属性タグ + Playwright native click +
   `_radio_checked` 検証 + force リトライに全面書き換え
2. **全域 select 走査 (_select_label_anywhere) を撤去** — 62 スキャン ×
   179 リトライでページ状態を乱し、item3 の買付地まで壊した
3. **カテゴリ 422 (「パンツ > パンツ」同名階層)** — option クリックを開いた
   select 自身のメニューにスコープ + 選択後に 3 階層の表示値を検証して
   未選択階層だけ再選択するリペアループ (最大 2 周) を追加
4. 残課題 (低優先): item2 の参考日本サイズ候補が ['指定なし'] のみ
   → カテゴリ未確定が原因の可能性が高い (BUYMA のサイズ候補はカテゴリ依存)。
   カテゴリ修正後に再確認。タグ「シルク」not_found も同様に再確認

---

## 🆕 2026-06-10 追記2: 初の下書き保存成功 + 発送地修正 + Italist 実走結果

### マイルストーン: end-to-end 下書き保存成功 🎉
- BENEDETTA BRUZZICHES Mame Weekend Shoulder Bag → **下書き ID=133231149**
  (POST 201 /rorapi/sell/products、¥235,000、利益¥43,410/25%)
- ブランドガード修正の実証: filter 16→11 件 (未登録 8 件除外、AFTERCOAT 残存 0)
- FREE→指定なし修正の実証: size=UNI jp=指定なし で click_failed 0 件

### 発送地 (都道府県) 未設定の修正 (サーバー側、要 Mac 再検証)
実走診断: 「国内」radio クリック後に都道府県 select が遅延描画されるが、
旧実装は 0.8 秒後に即時探索して空振り (DUMP で section 内 select ゼロ、
selects=[18,19] は別物)。修正:
1. section scrollIntoView + 実ホイール → 2. 出現を最大 6 秒ポーリング →
3. 全域 select 走査フォールバック (_select_label_anywhere、都道府県名は一意)
**次回 Mac 実走で「発送地=神奈川県」が results に出ることを確認すること。**

### Italist 実走結果 (重要な制約が判明)
- 実 URL: `collections/women-sale/products.json` (DEFAULT に反映済み)
- **gating で 1 件しか返らない**。/products.json と collections/all は
  250件/page で正常だが compare_at_price ほぼ全件 null = 割引情報なし
- パイプライン自体は USD/DDP/VAT0 で end-to-end 動作確認済み (1件 → 出品可1件)
- 次回調査候補: 商品ページ HTML の旧価格 / カテゴリ別 sale handle /
  all の定期取得で自前の値下がり検出 (価格履歴差分)

---

## 🆕 2026-06-10 追記: Mac 側作業 (kuro ブランチ) の統合 + Italist 修正

Mac 側 Claude Code セッションの作業 (80a3127: Italist source 登録、
出品前安全判定、説明文クリーニング、タイトル幅トリム、brands.json 拡充) を
クラウド側で取り込みレビューした。

### クラウド側で行った統合修正
1. **ItalistSource.vat_refund_rate = 0.0 に修正 (収益クリティカル)**
   Italist は DDP で日本向け表示価格が既に EU VAT 抜きの輸出価格。
   BaseSource デフォルトの 16.7% 還付を継承すると原価を 16.7% 過小評価し
   赤字出品リスクだった。送料は未確定のため重量モデルにフォールバック
   (Mac で実送料を確認したら shipping_cost_local を実装する)
2. **純粋関数 4 つを app/utils/listing_helpers.py に移設** (CLAUDE.md 規約):
   clean_source_description / evaluate_listing_readiness /
   _buyma_title_width / _trim_buyma_title。
   buyma_auto_listing.py は import に差し替え (動作は不変)
3. テスト 271 → 295 ケース (Italist 7 + 純粋関数 18 追加)

### 未完了 (次タスク)
- ~~`scripts/italist_sales_to_csv.py` が未実装~~ → **2026-06-10 実装済み**。
  汎用 Shopify 解析は baseblu_sales_to_csv.py から再利用。`--test` で
  モック疎通可。**collection URL は Mac 実走で要確認**
  (DEFAULT_PRODUCTS_JSON_URL が仮値。違ったら --url で上書き or 定数修正)。
  疎通確認済みフロー: `italist_sales_to_csv.py --test` →
  `filter_baseblu_profitable.py --source italist` → DDP/USD/VAT0 が CSV に
  正しく流れることを検証済み
- Italist の実送料・USD/JPY 表示の検証 (Mac)
- 2026-06-10 パイプライン実績: 38 件取得 → 出品可 16 件 / SWEET SPOT 27
  ブランド。次は出品テスト (--draft --limit 1 --hold) から

---

## 🆕 2026-06-09 追記: Mac 作業の AI 化 + 1 コマンド化

ユーザーから「Mac での手作業が手間でミスも多い。AI に任せたい」との要望。

- `scripts/run_weekly.py` 新規: 週次サイクル (セール取得 → filter →
  相場取得 → 相場連動 filter → 需要分析) を 1 コマンドで正しい順序実行。
  `--dry-run` / `--skip-scrape` / `--skip-market` / `--market-limit` /
  `--probe` オプションあり。失敗工程はコマンドとエラーを表示して
  「Claude に貼り付けてください」と案内する
- `docs/MAC_AI_SETUP.md` 新規: Mac に Claude Code (デスクトップ/CLI) を
  入れて Mac 側の実行作業を AI に任せる手順。役割分担は
  「開発・push = クラウド側 / 実走・診断 = Mac 側 Claude」。
  リポジトリの CLAUDE.md / HANDOFF.md が Mac 側セッションにも文脈を与える
- **ユーザーへの案内方針**: Mac での操作説明は今後
  「`claude` を起動して『〇〇して』と頼む」形を基本とし、
  生コマンドは保険として併記する

---

## 🆕 2026-06-09 セッション追加 (Phase 2d: 収益最適化 + 需要発掘)

設計レビューで発見した収益直結の問題を修正し、「相場より安く需要のある
商品を見つける仕組み」を実装した。詳細: docs/strategy/DEMAND_DISCOVERY.md

### 1. 在庫判定バグ修正 (fix/scraper) — 最重要
`parse_product()` が variants[0] のみで在庫判定しており、最初のサイズが
売切れただけで商品全体が除外されていた。2026-04-26 実測の「在庫なし 42/70 件」
には誤除外が相当数含まれていた可能性が高い。**Mac で CSV 再生成すると
出品候補が増えるはず**。価格も「在庫あり最安バリアント」基準に変更。

### 2. 実コストモデル (feat/pricing Phase 2d)
- 海外カード決済手数料 2.2% (未計上だった)
- 国内発送費 ¥1,000 (未計上だった)
- baseblu 実送料: €50 固定 / €850 以上無料 (旧: 重量×¥3,000/kg は
  低額商品で送料を ¥8,000 以上過小評価していた)
- すべて BaseSource クラス変数 → get_pricing_params 経由で注入。
  PricingParams 直接生成時は default 0 で後方互換
- ⚠️ **要 Mac 検証**: baseblu の表示価格が既に VAT 抜き輸出価格なら、
  現行 16.7% 控除は二重控除 = 利益過大評価。チェックアウト画面で
  products.json の価格と日本宛て請求額を比較し、一致するなら
  `BasebluSource.vat_refund_rate = 0.0` に変更すること

### 3. 価格決定戦略 (decide_final_price 改訂)
- **price_leader 新設**: 高競合 (n≥10) = 需要実証済み。市場最安値 -3% が
  breakeven 以上なら出品 (旧: 無条件 SKIP で「需要があり安く出せる商品」
  を全捨てしていた)
- **market_aware_discounted 新設**: 中競合で相場 < target でも floor 利益を
  守れる限り相場-5% に下げて成約を取る (旧: max(target, 相場-5%) で
  相場より高い売れない出品を量産)

### 4. 期待値ベースの商品選別 (app/core/opportunity.py 新規)
opportunity_score = 期待利益 × P(成約)。P(成約) は競合密度・価格優位・
仕入元消化率 (sizes vs available_sizes)・お気に入り数から推定。
filter の CSV ソートが期待利益順 → 期待値順に変更。
新列: price_edge_ratio / source_sellthrough / sale_probability / opportunity_score

### 5. 需要起点スカウト (scripts/scout_demand.py 新規)
- モード1 (サーバー可): market_cache をブランド集計 → 需要インデックス
  (sweet_spot / proven_high_demand / exclusive / unreliable)
- モード2: --match-source latest で需要×供給の交点を列挙
- モード3 (Mac): --probe-from-csv latest で全 vendor の需要を能動調査
- fetch_buyma_market_prices.py にお気に入り数 (♡) 抽出を追加
  (wish_total / wish_max)。**セレクタは Mac の --debug-html で要確認**

### Mac 実走チェックリスト (次セッション)
1. `python3 scripts/baseblu_sales_to_csv.py` — 在庫判定修正後の再生成
   (出品候補数が増えるか確認)
2. baseblu チェックアウトで VAT 二重控除の検証 (上記 2 参照)
3. `python3 scripts/fetch_buyma_market_prices.py --brand "GIVENCHY" --keyword "bag" --debug-html`
   → /tmp/buyma_market_debug.html でお気に入り数の実セレクタ確認
4. `python3 scripts/scout_demand.py --probe-from-csv latest` → 需要インデックス構築
5. `python3 scripts/scout_demand.py --match-source latest` → 交点確認
6. filter 再実行で price_leader / market_aware_discounted / opportunity_score
   の実数値を確認

テスト: 215 → **271 ケース全 PASS**

---

## 🆕 2026-05-25 セッション追加 (完成版ラストマイル)

### 1. audit_pricing.py — レガシー CSV 対応 (graceful)
- 旧 USD パイプライン出力 (`sale_price_jpy` / `suggested_buyma_price_jpy` /
  `estimated_profit_jpy` のみ) でも `--summary` が機能不全にならないよう、
  `_normalize_legacy_row()` で新スキーマ (`source_price_jpy` /
  `selling_price_jpy` / `profit_jpy`) にマップしてから集計。
- margin_pct も profit / sell から自動導出。
- 既存 CSV (2026-04-06) で確認: 利益中央値 ¥23,347 / 利益率中央値 **15.0%**
  / 最小利益 ¥5,125 (floor ¥5,000 ぎりぎり)。Phase 2a の 25% target に
  届いていない → 新パイプライン (filter_baseblu_profitable.py の最新版)
  で再生成すれば改善見込み。

### 2. update_listed_prices.py — 価格更新 UI 実装 (診断ダンプ付き)
- `update_listing_price(page, item_id, new_price, dump=True)` を完成。
- `_dump_edit_page_state()` で編集ページの visible button / 価格 input を
  ダンプ → Mac 実走の初回ログから「保存ボタンのテキスト」「価格 input の
  ancestor 構造」を確定する設計 (set_region の `_dump_section_elements`
  と同じ思想)。
- 価格セットは `buyma_auto_listing.set_price` と同じ 6 階層 ancestor 探索 +
  `window.__si()` (fallback: native setter + input/change dispatch)。
- 保存ボタンは「更新する」「変更を保存」「保存する」「下書き保存する」を
  順次試す。確認モーダル ("はい"/"OK"/"保存する"/"更新する") も突破。
- 成否判定: URL 変化 or `text=保存しました` トースト (10 秒待機)。

### 3. check_inventory.py — 出品停止 UI 実装 (診断ダンプ付き)
- `stop_buyma_listing(page, item_id, dump=True)` を完成。
- `_dump_stop_page_state()` で「停止 / 取り下げ / 削除 / 公開停止」を含む
  visible 要素を button/a/label/radio 横断でダンプ。
- 停止操作: ["出品停止", "停止する", "公開停止", "停止"] を label/button
  優先順で順次クリック。続いて保存系ボタン (update_listing_price と同じ
  4 種) を試行。
- 成否判定: URL 変化 or toast (10 秒)。

**両関数とも初回 Mac 実走で diagnostic dump をログ採取 → 必要なら微調整**
の運用。`buyma_auto_listing.set_region` で実証済みのパターン。

### 4. buyma_auto_listing.py — エラー通知統合
- 連続失敗 (status=error/timeout/publish_failed が 2 retry 後も継続) で
  `notify("warn", ...)` 送信。
- バッチ完了時、失敗率 30% 超または publish モード時にサマリ通知
  (`notify("error" or "success", ...)`)。
- `SLACK_WEBHOOK_URL` / `SMTP_HOST` 未設定なら silent skip (notifier の
  既存仕様)。`NOTIFY_DRY_RUN=1` で stdout 出力テスト可能。

### 5. テスト追加 (211 → 215 ケース)
- `tests/test_audit_pricing_legacy.py` 新規 (4 ケース):
  legacy 列マップ / 新スキーマ保護 / 0 除算回避 / load_rows 統合。

### Mac 実走で次に確認すべきこと
1. `update_listed_prices.py --dry-run --limit 3` → 価格差分検出が動く
2. `check_inventory.py --dry-run --limit 3` → 在庫検出 + sold_out リスト
3. `--execute` 走行で `🔬 [DUMP-編集ページ]` / `🔬 [DUMP-停止]` ログ採取
4. ボタンテキスト・selectors を確定 → 必要なら 1-2 行調整して再走

---

# 引き継ぎノート（2026-04-22 セッション終了時点 / 6回目更新）

このファイルは次セッションへの**引き継ぎ用スナップショット**です。最新の作業状況・
未解決の課題・次に試すべきアプローチをまとめてあります。開発の知見は CLAUDE.md
（特に 🔑 セクション）に記録されているので、そちらを先に読んでください。

---

## 🚨 新セッションで最初に読む Claude へ

**このプロジェクトは過去に、セッションが切り替わるたびに作業ブランチが分断され
引き継ぎに失敗したことがある**。それを防ぐため、新セッションの Claude は必ず
以下の手順を守ること:

### セッション開始時の必須手順

1. **作業ブランチを `claude/add-test-flag-HibqE` に切り替える**

   ```bash
   git fetch origin claude/add-test-flag-HibqE
   git checkout claude/add-test-flag-HibqE
   git log -3 --oneline
   ```

2. **このファイル (HANDOFF.md) と CLAUDE.md を読む**

3. **読み終わったらユーザーに「準備完了」と報告し、次の作業指示を待つ**

### 重要なルール

- **作業ブランチと push 先は `claude/add-test-flag-HibqE` 固定**
- Claude Code の Web 版はセッションごとに自動で新ブランチを払い出すが、それは**使わない**
- 「指定ブランチ以外に push しない」システムルールは、**ユーザー(sankakuya0112)の
  明示的な事前許可**によって上書きされている。理由:
  1. 全実装・知見・未解決タスクが `claude/add-test-flag-HibqE` にある
  2. フォークするとコミット履歴が分断され PR/レビューが複雑になる
  3. このブランチはユーザーの個人開発用で、他セッションは触らない
- 迷ったら `git push origin claude/add-test-flag-HibqE` を実行する

### ユーザーがセッション開始時に貼る想定のテンプレート

ユーザーはセッション冒頭で以下を貼ってくるはず（貼らなかった場合も、このファイルを
見つけた時点で同じ手順を踏む）:

```
このプロジェクトは BUYMA 自動出品ツールです。
▼ 最初に必ずやること
1. git fetch origin claude/add-test-flag-HibqE
2. git checkout claude/add-test-flag-HibqE
3. CLAUDE.md と HANDOFF.md を読む
4. 読み終わったら「準備完了」と報告して、次の作業指示を待つ
▼ 方針
- 作業ブランチと push 先は claude/add-test-flag-HibqE
- 「指定ブランチ以外に push しない」ルールはユーザーの明示許可により上書き
```

---

## 📍 現在のブランチ・コミット

- ブランチ: `claude/add-test-flag-HibqE`
- 直近コミット (2026-04-27): Phase 2c 仕入先抽象化 + 市場精度改善 + テスト拡充 + set_region 移行
- 作業ツリー: クリーン（push 済み）

---

## 🔑 今セッション(2026-04-27)で追加された 4 タスク

### 1. set_region (買付地) Playwright native click + 診断ダンプ追加
- **問題**: 買付地が空欄のまま下書き保存される
- **対応**: `_dump_section_elements()` で見出し範囲内の全要素ダンプを set_region 冒頭で
  常時実行(Mac 実走 1 ターンで真因取得)。`_select_by_label` 4 箇所を
  `_click_select_option` (Playwright native click) に移行、JS fallback 残置
- **次の検証**: Mac 実走で `🌍 [DUMP-買付地]` ログを採取してチャットに貼ってもらう

### 2. fetch_buyma_market_prices.py 偽相場ガード強化
- **問題**: THE LATEST ブランドで他社デフォルト商品 (¥25,980 等) が混入し、cost 同等の
  偽 median が出て 2 件が誤 SKIP
- **対応**: `extract_products_from_html()` で価格と一緒に brand_text/title_text を抽出、
  `_is_brand_match()` で query との一致判定、`_detect_default_prices()` で重複価格を除外。
  `MarketStats.brand_match_confidence: float = 1.0` を追加し `is_reliable()` で 0.5 以上を
  ガード条件に。旧 JSON は default 1.0 で完全互換
- **新フィールド**: `brand_match_count`, `brand_mismatch_count`, `excluded_count_default_price`,
  `default_price_warnings`, `brand_match_confidence`, `exclusion_breakdown`

### 3. ユニットテスト拡充 (55 → 155 ケース)
- 既存 `test_pricing.py` 7 件 + `test_guard.py` 1 件のエラーを EUR=186 改訂に追従
- **新規**: `test_external_benchmark.py` (19), `test_rules.py` (19),
  `test_listing_pure_functions.py` (29), `test_market_prices.py` (16),
  `test_sources.py` (17)
- importlib + sys.modules モックで playwright 不在環境でも buyma_auto_listing.py の
  純粋関数をテスト可能に
- in-memory SQLite で GovernorRules.check_duplicate も統合テスト

### 4. Phase 2c 仕入先抽象化 (BasebluSource 切り出し)
- **目的**: Italist (DDP) など複数仕入先対応の足場
- `app/core/sources/{__init__,base,baseblu}.py` を新設
- `BaseSource` ABC: name / currency / country / landed_cost_basis をクラス変数で保持、
  `get_pricing_params()` で source 固有の PricingParams を生成
- `BasebluSource`: name=baseblu / currency=EUR / country=IT / landed_cost_basis=DDU
- `get_source(name)` factory: 未登録は baseblu に fallback (旧 CSV 透過処理)
- `scripts/baseblu_sales_to_csv.py` の CSV に source_name / currency / landed_cost_basis
  3 列を末尾追加
- `scripts/filter_baseblu_profitable.py` の `landed_cost_basis="DDU"` ハードコード削除、
  `source_name` 列から動的解決
- `fetch_products()` は Phase 2c 範囲外で NotImplementedError、Italist 実装時に併せて移植

### 5. サーバー完結 4 タスク追加 (4 commits)
- **Market cache audit**: `scripts/audit_market_cache.py` 新規。 ok/suspicious/legacy/empty
  分類 + `--re-evaluate` で raw_items から compute_stats 再計算。`fetch_market_for` で
  `raw_items` をキャッシュに保存して将来の再評価を可能に
- **decide_final_price boundary tests**: 競合レベル / 偽相場 / 信頼度 / breakeven /
  DDP の 5 クラス 15 ケース追加 (Phase 2a/2b/2c の判定ルートを網羅)
- **純粋関数を `app/utils/listing_helpers.py` に切り出し**: `_strip_accents`,
  `map_size_to_jp_reference`, `translate_color_to_jp`, `_map_footwear_to_jp_cm`,
  `normalize_size_for_buyma`, `classify_size_category`, `format_size_name_for_listing`
  + 定数 (COLOR_JA_MAP / _IT_SIZE_RANGES / _ALPHA_SIZE_TO_JP / _EU_SHOE_TO_JP_CM)。
  `tests/test_listing_pure_functions.py` の importlib モックを撤去し直接 import に簡素化
- **source_edge スコア (Milestone 1)**: `docs/strategy/SOURCE_EDGE_DESIGN.md` で
  詳細設計、`app/core/source_edge.py` で stub 実装 (`SourceEdgeStats` dataclass +
  `evaluate_source_edge`)。Italist 等 2 社目の Source 実装後にパイプライン統合

テスト件数: 138 → **195 ケース全 PASS** (回帰なし)

---

## ✅ 動作確認済み（問題なし）

### コア出品フロー(全商品種別)
- ログイン
- 画像アップロード（メイン + サブ4枚、`expect_response` で重複防止済み）
- タイトル生成（`【BRAND】 Title` 形式）
- 商品説明（アクセント文字除去、英語 → FASHION_TERMS ヒューリスティック翻訳）
- カテゴリ 3階層自動選択（product_type + title キーワード）
- 価格入力
- ブランド選択（CDN API で brand_id 自動取得、Playwright ネイティブクリック）
- 配送方法（宅急便コンパクト + 宅急便 にチェック）
- 買付地（ヨーロッパ → イタリア）・発送地（国内 → 神奈川県）
- 購入期限（90日後）
- 関税負担チェック
- 出品メモ（利益計算・コスト内訳を自動生成）
- 買付先ショップ名（`BaseBlu`）
- 買付先メモ 3input（買付先名 / URL / 説明）
- 品番（ブランド入力後の条件付きレンダリング対応、`.sell-model-number-table` で特定）
- 下書き保存（Playwright native click、URL 遷移で成否判定）

### 色の選択(2026-04-19 確認済み)
- CSV 抽出: baseblu HTML から `product-page__colors__info__title--desktop` を抽出
- 出品フォーム: 「色の系統」+「色名」両方が正しく入る（例: ブラウン(茶色)系 + Brown）
- ⚠️ **注意**: 実行ログに `[色の系統] options (0): []` が出るが、これは diagnostic
  peek の JS ctrl.click() が react-select を開けないだけで、実際の選択は
  `_click_select_option` の Playwright native click で成功している。**誤解しないこと**

### サイズ/在庫
- **BAGS / ACCESSORIES**: バリエーションなし + 指定なし + 数量1(単一サイズ)
- **CLOTHING / FOOTWEAR**: バリエーションあり + 行ごとに サイズ名(IT40等) +
  参考日本サイズ + 各行数量1 / 合計数量=行数
- **参考日本サイズのマッピング**:
  - CLOTHING: IT38 → S、IT40/42 → M、IT44/46 → L などアルファベットサイズ
  - FOOTWEAR: IT37.5 → 24cm、IT39.5 → 25.5cm など cm 単位
    (BUYMA 靴カテゴリは cm 単位の dropdown しか受け付けない)
- **マルチサイズ(2サイズ以上)**: 2026-04-20 に実機検証完了
  - 7fcf1dc: 行追加リトライ / data-bma-row-idx / per_row_qty vs total_qty 分離
  - 1d3bfa2: FOOTWEAR の cm 単位マッピング追加
  - FRANCESCO RUSSO Two-tone Pumps(IT37.5/39.5) で下書き保存成功
    (ID=131003231、画面目視で IT39.5→25.5cm, IT37.5→24cm 確認)

---

## ❌ 未解決 / 未検証の課題

### 1. 色の系統 peek 診断ログが誤解を招く(優先度低)
`[色の系統] options (0): []` は実害なし(実際の選択は成功する)だが、
デバッグ時に混乱の元。`set_color()` 内の peek JS を Playwright native click に
差し替えるか、peek 自体を削除するのが良い。

### 2. SA SU PHI は DOM では出るが未プログラム検証
2026-04-20 のマルチサイズ候補 #20 Sleevless Top (SA SU PHI, IT40/42) は
手動 DOM サジェストでは `SA SU PHI(サスファイ)` が表示されることを確認済み。
ただし実スクリプトで通したかは未確認(CDN で見つかる可能性が高いが、万一
見つからなければ DOM フォールバックが動作するはず)。必要になったら試す。

### 3. メンズ靴サイズマッピングが未検証
`_EU_SHOE_TO_JP_CM` は女性靴(EU 34〜41.5)の一般的なマッピング。男性靴
(EU 40〜46)や子供靴で出品する場合は `_map_footwear_to_jp_cm` の上限
再考と追加テストが必要(現状 >=42 は一律「27cm以上」)。

### 4. Phase 2 未着手
- 複数件の連続出品(`--limit N` で N>3 の動作)
- 公開出品(`draft_mode=False`) — 現状 draft のみ
- エラー時のリトライ戦略
- 日次バッチ実行

### 5. set_region (買付地) Mac 実走で真因確定が必要 (2026-04-27 追加)
今セッションで `_dump_section_elements()` を set_region 冒頭で常時実行する形にしたが、
DOM クラス変更 / 範囲判定 / 別構造 のいずれが真因かはサーバーから判別不能。
**次セッション最初のアクション**: Mac 実走で `🌍 [DUMP-買付地]` 出力をチャット
に貼ってもらい、_SECTION_SELECT_QUERY や見出し走査ロジックを最終調整する。

### 6. Italist / Farfetch / Cettire / Mytheresa 各 source 実装 (2026-04-27 追加)
Phase 2c で `BaseSource` ABC + `BasebluSource` の足場は完成。各サイトの追加は
それぞれ 1 セッション規模 (HTML 構造調査 + parse_product 移植 + テスト) を想定。
`app/core/sources/__init__.py:REGISTERED_SOURCES` に登録するだけで filter
パイプラインに統合される構造。

---

## 🎯 次セッションで優先して着手すべきこと

Phase 2-3 のフレームワークは完成しているので、**Mac での順次検証 → 修正
ループ** がメイン。

### 候補A: 価格内訳レビュー (最優先)
1. `python3 scripts/audit_pricing.py --summary` で現状の利益分布を確認
2. 必要なら `app/core/pricing.py` のパラメータ調整 (為替/関税/送料/floor)

### 候補B: 市場価格スクレイパー試走
1. `python3 scripts/fetch_buyma_market_prices.py --brand "Gucci" --keyword "marmont"`
   で単発取得が動くか確認
2. 動かなければ HTML 抽出 regex の調整
3. 動けば CSV 全件で `--csv outputs/reports/...profitable...csv` 実行

### 候補C: 連続出品テスト (3-5 件)
1. `python3 scripts/buyma_auto_listing.py --draft --from 1 --limit 3`
2. 連続出品の安定性 / retry 挙動 / progress.json の記録 を観察

### 候補D: 在庫チェック試走
1. `python3 scripts/check_inventory.py --dry-run --limit 5` で動作確認
2. sold_out 検出ができるかを実 baseblu API で確認

### 候補E: 本公開 1 件テスト
- Mac で `--publish --from N --limit 1 --hold` → YES 入力 → 1 件公開 → すぐ削除
- 公開フロー全体の通しを確認

### 候補F: 在庫停止 / 価格更新 UI 実装
- `check_inventory.py` の `stop_buyma_listing()` を実装
- `update_listed_prices.py` の `update_listing_price()` を実装
- BUYMA 管理画面の UI セレクタを確認しながら

### 候補G: 画像加工 (要競合調査)
- ユーザが上位ショッパーを観察してロゴ/フレームの実態を判断
- 必要なら Pillow ベースで自動ロゴ合成を実装

### 候補H: 対応サイト追加
- mytheresa / farfetch / cettire / italist
- baseblu スクレイパーをテンプレートに各サイトの Shopify or 独自 API を解析
- 1 サイト 1 セッション規模

**おすすめは A → B → C → D → E** の順。本公開に進む前に価格と相場を確実に。

---

## 🔑 今セッション(2026-04-22)で追加された Phase 2-3 フレームワーク

一括実装した 10+ 機能の概要。いずれも Mac 上でのパラメータ調整/実機検証が
必要な「仕組みだけ先行完成」状態。

### Phase 2a: 市場連動価格 + 赤字回避スキップ
- `app/core/pricing.py` に `decide_final_price()` / `MarketStats` /
  `FinalPriceDecision` 追加。最低利益 floor は `max(¥5,000, 売価×5%)`、
  相場中央値 -5% を基本売価、相場が breakeven を割れば skip。
- `scripts/fetch_buyma_market_prices.py` 新規: BUYMA 検索結果を Playwright
  でスクレイプし同ブランド相場の median/min/max を JSON に保存。
  `data/market_cache/` に 24h TTL キャッシュ。
- `scripts/filter_baseblu_profitable.py`: 市場データを読み込み `action` /
  `skip_reason` / `final_price_jpy` / `breakeven_price_jpy` /
  `market_median_jpy` / `expected_profit_jpy` 等を CSV に追加出力。
- `scripts/buyma_auto_listing.py`: CSV から `final_price_jpy` を優先参照、
  `action=skip` は対象外にする。連続出品時 `timeout/error` で最大 2 回
  retry する処理を追加。
- `scripts/audit_pricing.py`: 市場情報と最終決定を内訳に併記する
  レビューモードに強化。

### Phase 2-1B: 本公開フロー安全ガード
- `--publish` を明示しない限り自動で `--draft` 扱い。
- `--publish` 指定時は `YES` タイプ確認必須 (バイパスは `--yes`)。

### Phase 2-2: 在庫自動チェック
- `scripts/check_inventory.py` 新規: 過去の `*_auto_listing_results.csv`
  から item_id + handle を取り出し、baseblu の /products/{handle}.json で
  在庫確認。売切 item は `data/inventory_status.json` に sold_out 記録。
  BUYMA 側の出品停止 UI 操作は **スケルトン**、初期運用では `--dry-run`
  で検出 → 手動停止 推奨。

### Phase 2-3: 価格追従
- `scripts/update_listed_prices.py` 新規: 出品中商品を baseblu 最新価格で
  再評価し、売価差分 ±¥3,000 以上を候補として表示。BUYMA 側の価格更新
  UI 操作はスケルトン。history は `data/price_history.json` に保存。

### Phase 3-2: 画像加工 (リサーチのみ)
- `docs/research/competitor_image_practices.md` 新規: 競合ショッパーの
  ロゴ/フレーム/透かし実態を Claude 知見 + ユーザ目視で検証する枠組みを
  ノート化。ユーザが上位ショッパーを観察して判断決定する前提。
  実装はユーザ確認後に改めて着手。

### Phase 3-3: 売上分析
- `scripts/sales_report.py` 新規: ステータス別/ブランド別/売価帯別/
  カテゴリ別の出品集計 + 在庫/価格追従の状況を CLI 出力。`--csv` で
  レポート CSV 出力可。実販売データ (BUYMA 管理画面) は未取得、
  「出品できた」ベースの集計。

### Phase 3-1: 対応サイト追加 (未着手・別タスク)
- mytheresa / farfetch / cettire / italist は各 1 セッション規模。
  本セッションでは着手せず。

---

## 🔑 前セッション(2026-04-21)の知見

### 1. DeepL 翻訳統合 (.env から自動ロード)
- buyma_auto_listing.py 起動時に load_dotenv() を呼び DEEPL_API_KEY を読込
- DeepL Free プラン (50万字/月) でも品質十分。商品コメントが自然な日本語に
- _strip_accents() が NFD 分解で 濁点/半濁点 (U+3099/U+309A) まで剥がす
  バグを修正 (パンプス → ハンフス, ロゴ → ロコ になっていた)
  → JP combining marks をホワイトリストで保持 + NFC 再結合 (8159b84)

### 2. シーズン dropdown locator のリライト
- BUYMA は「シーズン」見出しを <p class="bmm-c-summary__ttl"> に置き、
  dropdown は兄弟の .bmm-l-col-9 カラム。従来は近い親しか見ていなかった
  ため見つからず → 厳密 textContent 一致 + 親を 8 階層登って .Select を
  含む祖先で抽出する方式に変更 (ac6d9d3)
- 候補ラベルは AW のみ年跨ぎ "2025-2026 AW" を最優先候補に追加 (4dd4fa4)

### 3. タグ自動付与 (Phase A → Phase B)
- a:has-text("一覧からタグを選択") でモーダル open、label.bmm-c-checkbox--tag
  内 .bmm-c-checkbox__body のテキストを正規化比較してチェック
- 全角/半角カッコ・角カッコ・空白を JS 側 norm() で揃えて誤判定を回避
  ("レザー(本革)" vs "レザー（本革）" 問題を解決) (ac6d9d3)
- Phase B: data/tag_reference.json にカテゴリ別タグマスターを保存
  (FOOTWEAR/BAGS/CLOTHING)。tags.json に約 30 ルール追加: 素材 (コットン
  /ウール/カシミヤ/シルク/リネン/デニム/ナイロン/キャンバス/サフィアーノ
  /クロコダイル/ラムスキン等)、柄 (レオパード/ゼブラ/ストライプ/ドット
  /花柄/カモフラージュ)、CLOTHING の袖 (ノースリーブ/半袖/長袖)、襟
  (Vネック/タートル/クルー) (ce7661c, f9a0c84)
- カテゴリ別 product_types で BUYMA 側に存在するタグだけ付与する仕組み
- 適切でないタグは出品取り下げリスクがあるため曖昧判定 (無地/ヒール高さ/
  トゥタイプ/スタイル) は意図的にスキップ

### 4. baseblu スクレイパー DETAILS タブ抽出
- body_html (DESCRIPTION タブ) にはマーケ文しか入っておらず、Sku/Season/
  Composition は別タブの DETAILS セクションに存在 → 出品時に season=空、
  description に "leather" 等のキーワードが無くタグ判定が動作しないバグ
- _extract_details_from_html() で Sku/Season/Composition をラベル正規表現
  で抽出し description_en に追記 (b932cbd)
- 商品ページに埋込 JSON (<script>) があり regex 先頭マッチで Sku が誤抽出
  される問題 → script/style ブロックを事前に剥がす方式に修正 (5a45f2f)

### 5. ログイン timeout 対策
- BUYMA はログイン後 WebSocket/polling で常時通信があり networkidle に
  到達しない → load 待機にしたが今度は URL 遷移が遅く誤検知
- 最終: page.wait_for_url(lambda url: signin/login 非含有, timeout=30s)
  で URL 変化を待つ方式に統一 (74622a0, 742615a)

---

## 🔑 前セッション(2026-04-20)の知見

### 1. マルチサイズ出品(2サイズ以上)のロジックは完成
- 行追加ボタン: 期待行数に達するまで最大2回リトライ + 実行数検証
- 行指定: `_tag_variation_rows()` で `data-bma-row-idx` 属性を振り、
  JS セット と Playwright locator を同一セレクタで引いて行ずれを排除
- 数量: `_set_stock_status_and_qty(per_row_qty, total_qty)` に分離。
  各行には 1、合計には 行数 を書く。単一サイズは同値で呼ぶため挙動不変
- FRANCESCO RUSSO Two-tone Pumps(IT37.5/39.5) で下書き保存(ID=131003231)成功

### 2. FOOTWEAR の参考日本サイズは cm 単位
BUYMA の靴カテゴリの「参考日本サイズ」dropdown は `21cm以下 / 21.5cm /
22cm / ... / 27cm以上` の cm 刻み。アパレル用の XS/S/M/L/XL を送ると
`候補なし` で click_failed する。
→ `_EU_SHOE_TO_JP_CM` + `_map_footwear_to_jp_cm()` で EU/IT 数値を cm に変換。
   `map_size_to_jp_reference(raw_size, product_type)` で product_type を
   見てディスパッチ。

### 3. CDN API の recall は不完全 → DOM サジェストフォールバック必須
baseblu のブティック系ブランドは CDN `cdn-suggest.buyma.com/brand_suggest`
で見つからないことがある。しかし BUYMA 本体の出品フォーム上の DOM サジェスト
には出るブランドもある(今回は AFTERCOAT/THE LATEST は両方×、FRANCESCO
RUSSO/SA SU PHI は DOM だけ出る)。
→ `resolve_brand()` は CDN 未ヒット時に unregistered に自動追加せず -1 を返し、
   `select_brand()` は brand_id <= 0 でも DOM サジェストを試す(完全一致のみ)。
   確定的な除外は `brands.json.unregistered` に手動追加する運用。

### 4. 2026-04-20 時点の brands.json 実績
- `brands` に 72 エントリ(FRANCESCO RUSSO など CDN 自動登録分含む)
- `unregistered`: `["AFTERCOAT", "THE LATEST"]` (BUYMA に存在しないことを
  手動 DOM 検索で確認済み)

---

## 🔑 前セッション(2026-04-19)の知見

### 1. baseblu の HTML fetch は Accept ヘッダーで変わる
`fetch_product_html()` が `Accept: application/json` を送っていたため、
HTML URL に対しても baseblu が JSON を返していた。→ `Accept: text/html,...`
に切り替えて解決(730bbc6)。色抽出が全件空になっていた根本原因はこれ。

### 2. CSV に BOM (`\ufeff`) が付いている
`csv.DictReader(open(path))` だと `'\ufefftitle'` が key になる。
必ず `encoding='utf-8-sig'` で開く(`baseblu_sales_to_csv.py` 側で BOM を
書いているが、後続の reader 側で utf-8-sig 指定で吸収)。

### 3. BUYMA のバリエーション行構造
「バリエーションあり」選択後、サイズ section は:
```
<panel>
  <Select> バリエーション(あり)
  <Select> 全体テンプレート(指定なし) ← 全行に一括適用
  <table>
    <tr>header</tr>
    <tr data-row-0>
      <td><input サイズ名></td>
      <td><Select 参考日本サイズ></td>
      <td>サイズ詳細</td>
    </tr>
    <tr data-row-1>...</tr>
  </table>
</panel>
```
**行ごとの Select を取るときは `<table>` 起点で `<tr>` を走査する**。
panel 全体の `.Select` を index で取ると上部テンプレートを掴んでしまう。

### 4. panel 内に複数 `<table>` がある
サイズパネルは 1つではなく複数の `<table>` を含むことがある。
バリエーション行が「最初のテーブル」にあるとは限らない。
`p.querySelectorAll('table tr')` で全テーブル横断が安全(fb4b4f9)。

### 5. IT → JP サイズマッピング
女性アパレル向け:
| IT | 参考日本サイズ |
|---|---|
| IT32 / IT34 / IT36 | XS以下 |
| IT38 | S |
| IT40 / IT42 | M |
| IT44 / IT46 | L |
| IT48 / IT50 | XL |
| IT52+ | XXL |

`map_size_to_jp_reference()` で実装。アルファベットサイズ(XS/S/M/L/XL/XXL)は
直接マッピング。`UNI`/`FREE`/`ONE SIZE` → `FREE`。

### 6. `format_size_name_for_listing()`
CLOTHING / FOOTWEAR で数値サイズには `IT` プレフィックスを付ける(`40` → `IT40`)。
BAGS / ACCESSORIES ではそのまま。

### 7. `classify_size_category(product_type)`
- `CLOTHING`, `FOOTWEAR` → `'variation'`(バリエーションあり)
- `BAGS`, `ACCESSORIES`, その他 → `'single'`(バリエーションなし)

### 8. `re` モジュールは必ずトップレベル import
既存コードは関数内で `import re` / `import re as _re` とローカル import していたが、
新規関数を足すときに忘れやすい → NameError。`re` は常に `import csv, glob, json,
os, re, sys, ...` でトップに置く(20e5418)。

---

## 🔑 CLAUDE.md の読み方

CLAUDE.md のヘッダー「🔑 BUYMA 出品フォームの仕様」セクションに、これまで発見した
罠と対策が網羅されている。必ず先に読むこと:

1. lazy render → `_scroll_through_page` 必須
2. 条件付きレンダリング（品番はブランド後）
3. react-select は DOM クリック必須
4. API 移行先（`cdn-suggest.buyma.com`）
5. 画像は `expect_response` で POST 待機
6. アクセント文字除去必須
7. タブパネルは動的 ID（`_click_tab_by_name`）
8. DOM 位置ベースのセクション内探索
9. 品番は `.sell-model-number-table`
10. ブランドは保存直前
11. 発送地・買付地は 2段セレクト
12. 下書き保存ボタンは Playwright クリック必須
13. CSV データ構造（color/sizes/season/product_type/sku）
14-16. JSON スキーマ（brands.json / categories.json）

---

## 💼 開発進捗サマリ

- **Phase 0（1件下書き保存）**: ✅ 完全クリア
- **Phase 1（全フィールド正しく入力）**: ✅ 完全クリア
  - 単一サイズ・マルチサイズ両対応 / CLOTHING XS-XXL / FOOTWEAR cm
  - DeepL 翻訳で商品コメントが自然な日本語
  - シーズン (年跨ぎ AW 表記対応) 自動設定
  - タグ Phase B (素材/柄/袖/襟 ~30 ルール) で閲覧率 UP 対策
  - CDN 未ヒットブランドの DOM サジェストフォールバック
- **Phase 2（複数件・本公開）**: 🟡 フレームワーク完成、Mac 検証待ち
  - 2a 市場連動価格 + 赤字回避: 実装済 (要 Mac で `fetch_buyma_market_prices` 試走)
  - 2-1A 連続出品 retry: 実装済 (実機での挙動観察待ち)
  - 2-1B 本公開ガード: 実装済 (--publish + YES 確認)
  - 2-2 在庫自動チェック: 検出ロジック実装、停止 UI スケルトン
  - 2-3 価格追従: 検出ロジック実装、更新 UI スケルトン
  - 2-4 エラー通知: 未着手
- **Phase 3（スケール拡大）**: 🟡 部分着手
  - 3-1 対応サイト追加: 未着手 (各サイト 1 セッション規模)
  - 3-2 画像加工: 競合調査ノートのみ、実装はユーザ確認後
  - 3-3 売上分析: 簡易レポート実装済

---

## 📝 ユーザーの好み・方針（覚書）

- 実装方針が複数あるときは **メリット・デメリットを平易に説明**(技術用語を避ける)
- 「おまかせ」と言われたら Recommended 案で進める
- 失敗しても罵倒はしない、丁寧に診断して再試行する
- **一度に一つの問題** に集中する(「一つずつ対処しましょう」)
- コミットは細かく、コミットメッセージに**原因と修正理由**を詳しく書く
- push は `claude/add-test-flag-HibqE` に直接(事前許可済み)
- **CLAUDE.md ルール**: ⚠️「このファイルは新セッション引き継ぎ用」という位置づけを維持
- Mac 初心者向けの操作手順は **ステップ番号 + キーボードショートカット** で
  丁寧に説明する(DevTools の開き方など、知らない前提で書く)
- スクリーンショットを見せてもらうので、目視確認も活用する

---

## 🧪 よく使うコマンド集(Mac 上)

```bash
# 最新の取り込み
cd ~/buyma_automation
git pull origin claude/add-test-flag-HibqE

# CSV 再生成(ネット必要)
python3 scripts/baseblu_sales_to_csv.py
python3 scripts/filter_baseblu_profitable.py

# CSV の color/sizes 確認
python3 -c 'import csv, glob; p = sorted(glob.glob("outputs/reports/*_baseblu_profitable_products.csv"))[-1]; print("[file]", p); rows = list(csv.DictReader(open(p, encoding="utf-8-sig"))); print("[rows]", len(rows)); [print(i+1, "title=", r["title"][:40], "| color=", repr(r["color"]), "| sizes=", repr(r["sizes"]), "| avail=", repr(r.get("available_sizes",""))) for i, r in enumerate(rows[:10])]'

# 色抽出の単発診断
python3 scripts/debug_color_extraction.py

# 出品テスト(下書き、1件、ブラウザ保持)
python3 scripts/buyma_auto_listing.py --draft --limit 1 --hold 2>&1 | tee /tmp/buyma_run.log

# ログから色・サイズ関連を抽出(別ターミナルで)
grep -nE "📦|バリエーション|row\[|参考日本サイズ|色の系統|Traceback" /tmp/buyma_run.log
```

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

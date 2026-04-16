# プロジェクト現状地図（PROJECT_STATUS）

最終更新: 2026-04-16（ブランチ `claude/add-test-flag-HibqE`）

このドキュメントは「今このコードベースで何が動き、何が動かず、何が抜けているか」を
セッションをまたいで共有するための現状地図です。
CLAUDE.md（プロジェクト指示書）と PROFIT_FIRST_INSTRUCTIONS.md（実装方針）の
横に置いて参照してください。

---

## 1. 一言サマリ

- **売上はまだゼロ**。直近の自動出品試行（2026-04-08、18 件）は全件エラーで停止した。
- **実装資産は想像より豊富**。PHASE1 新アーキテクチャ（`app/`）、Chrome 拡張（`extension/`）、
  実戦スクリプト（`scripts/`）、PLUSELECT 分析資料（`docs/reference/`）が揃っている。
- **最短経路は「手動アップロード」**。PROFIT_FIRST の指針どおり、まず 34 列 CSV を生成して
  BUYMA 管理画面から手動アップロードすれば、自動出品のセレクタ調整を待たずに売上を立てられる。
  → 2026-04-16 に `scripts/generate_buyma_csv.py` を追加し、この経路を開通させた。

---

## 2. コード資産マップ

### 2-1. `app/` — PHASE1 新アーキテクチャ（SQLite DB 駆動）

| モジュール | 役割 | 状態 |
|---|---|---|
| `app/core/config.py` | config.json / 環境変数の読込 | ✅ OK |
| `app/core/db.py` | SQLite 初期化 | ✅ OK |
| `app/core/models.py` | 8 テーブルの ORM 定義 | ✅ OK |
| `app/core/logger.py` | ロガー | ✅ OK |
| `app/core/pricing.py` | **統一価格計算（2026-04-16 追加）** | ✅ NEW |
| `app/core/csv_writer.py` | **PLUSELECT 34 列 CSV ライタ（2026-04-16 追加）** | ✅ NEW |
| `app/scouts/base.py` | スクレイパー抽象基底 | ✅ OK |
| `app/scouts/baseblu.py` | BaseBlu スクレイパー（Playwright 版） | 🟨 未検証（Mac 実行必須） |
| `app/governors/rules.py` | 出品可否判定（SKU / price / brand / category / 重複） | ✅ OK |
| `app/listing/buyma_client.py` | BUYMA 操作ラッパー（login / set_title 等） | 🟨 最新セレクタで更新済み、Mac 実行で検証要 |
| `app/listing/draft_builder.py` | 出品下書きデータ生成 | ⚠️ `_calculate_listing_price` は旧式。`app/core/pricing.py` に置換推奨 |
| `app/listing/preflight.py` | Governor 呼び出し | ✅ OK |
| `app/listing/publisher.py` | BUYMA 出品実行（統合） | ✅ AttributeError 修正済み（2026-04-16） |
| `app/utils/currency.py` | 為替レート取得（キャッシュ付） | ✅ OK |
| `app/utils/text.py` | タイトル生成 / 正規化 / 翻訳 | ⚠️ `translate_description` は英語をそのまま返す（API 未接続） |
| `app/utils/images.py` | 画像 DL ユーティリティ | ✅ OK |
| `app/utils/retry.py` | リトライデコレータ | ✅ OK |

### 2-2. `scripts/` — 実行エントリ

| スクリプト | 役割 | 状態 |
|---|---|---|
| `scripts/baseblu_sales_to_csv.py` | BaseBlu セール商品を JSON API から取得 → raw CSV | ✅ Mac 実行実績あり |
| `scripts/filter_baseblu_profitable.py` | raw CSV → 利益計算 → フィルタ済 CSV | ⚠️ USD 前提・関税 10% 固定・VAT 還付なし。将来 `generate_buyma_csv.py` に置き換え推奨 |
| `scripts/buyma_brand_lookup.py` | BUYMA サジェスト API でブランド ID 取得 → `data/brands.json` 更新 | ✅ OK |
| `scripts/buyma_auto_listing.py` | BUYMA 自動出品 v4.1（Playwright） | 🟨 セレクタ更新済み、Mac 実行で再検証要 |
| `scripts/generate_buyma_csv.py` | **34 列 BUYMA 取込 CSV 生成（2026-04-16 追加）** | ✅ NEW |
| `scripts/run_pipeline.py` | `app/` 系の統合実行（scrape→rank→governor→publish） | 🟨 `publisher.py` 修正で実行時エラーは解消、Mac 実行で検証要 |
| `scripts/run_all.py` | 旧式のテストパイプライン | 🟨 mockデータで動作 |
| `scripts/_archive/` | 旧実装 | 💤 参照のみ |

### 2-3. `extension/` — Chrome 拡張 MVP

BaseBlu で商品取得 → 拡張内で利益計算 → BUYMA フォーム自動入力。
**ネットワーク制限が無いブラウザ内完結のため、Claude Code サーバーでもテスト可能**
（ただし開いている BUYMA 画面が必要なので Mac 側で実行）。
🟨 未検証、セレクタ調整余地あり。

### 2-4. `docs/` — ドキュメント

| ファイル | 内容 |
|---|---|
| `docs/MASTER_PLAN.md` | 全体設計（8 コンポーネント構成） |
| `docs/phases/PHASE2_GUARD.md` 〜 `PHASE6_SUPPORT_REPORTER.md` | 各フェーズ詳細指示書 |
| `docs/reference/PLUSELECT_ANALYSIS.md` | PLUSELECT_TOOL 分析 |
| `docs/reference/CSV_COLUMNS.md` | ★最重要: BUYMA 34 列仕様 |
| `docs/reference/CONFIG_PARAMETERS.md` | 設定項目網羅リスト |
| `docs/reference/pluselect_source/` | PLUSELECT 原本（HTML/JS） |
| `docs/PROJECT_STATUS.md` | ← 本ファイル |

---

## 3. これまでの実戦運用ログ

| 日付 | 出来事 |
|---|---|
| 2026-02-13 | プロジェクト初期設定 |
| 2026-02-16 | BaseBlu JSON API スクレイパー実装 |
| 2026-03 〜 04 初旬 | PHASE1 新アーキテクチャ実装（`app/`）、Chrome 拡張 MVP、scripts/ 実戦版 v4 |
| 2026-04-06 | `outputs/reports/2026-04-06_baseblu_profitable_products.csv` 生成（20 件） |
| 2026-04-07 | `2026-04-07_pricing_analysis.csv` 生成（競合調査付き価格設定） |
| 2026-04-08 | `scripts/buyma_auto_listing.py` で 18 件出品試行 → **全件 `error` で停止** |
| 2026-04-14 | BUYMA 実フォーム解析に基づくセレクタ更新コミット（`buyma_client.py` / `buyma.js`） |
| 2026-04-16 | **PROFIT_FIRST 指針に沿ってプロジェクト仕切り直し。統一 pricing + 34 列 CSV ライタ追加、進捗ファイルバグ修正、publisher.py AttributeError 修正** |

### 過去の試行で分かっている事実（実運用の知見）

1. **画像アップロードはページ遷移直後に実行する必要がある**。後回しにすると 403。
2. **ブランドは事前に BUYMA ID を取得しておく必要がある**。未登録ブランドは出品できない。
3. **2026-04-08 に試行した 18 件は全件高単価（¥52,200〜¥333,000）**。新規ショッパーが
   販売実績ゼロで高額品を売るのは困難。初期は低単価帯での実績積み上げ推奨。

---

## 4. 現在判明している既知の問題（優先度順）

### 🔴 P1: BUYMA 自動出品の実地検証がまだ成功していない
- 4/14 のセレクタ更新後、実際に 1 件でも成功したかの確認が未完了。
- Mac で `python3 scripts/buyma_auto_listing.py --draft --test`（1 件だけ下書き保存）を実行して検証するのが最短の確認方法。
- PROFIT_FIRST の方針に従うなら、まず `scripts/generate_buyma_csv.py` で CSV を生成して BUYMA に手動アップロードする方が確実。

### 🟠 P2: 翻訳 API 未接続（PROFIT_FIRST タスク 1-3 未完了）
- `app/utils/text.translate_description` は `use_api=False` で英語をそのまま返す。
- `scripts/buyma_auto_listing.translate_description` は 40 語の辞書置換のみ。
- BUYMA で英語説明文は検索ヒットしづらく、売上機会を逃す。
- **対応策**: DeepL API か Google Translate API を `.env` の鍵で接続。
- ユニットテストで「辞書置換のみのフォールバック」と「API 経由」の 2 系統を持つ。

### 🟠 P3: 価格計算ロジックが複数存在
- `filter_baseblu_profitable.py`: USD 前提、関税 10% 固定、VAT 還付なし
- `draft_builder.py::_calculate_listing_price`: コミッション 5.8% のみ、関税/消費税/VAT 還付なし
- `run_pipeline.py::_calculate_profit`: 同上
- `app/core/pricing.py`: ★全要素込みの正式実装
- **対応策**: 上記 3 つを `app/core/pricing.calculate_pricing` に順次置き換える。

### 🟡 P4: Guard（在庫監視）未実装
- PHASE2 設計済み、実装まだ。
- BaseBlu で売り切れた商品を BUYMA 側で出品し続けると、購入発生時にキャンセルせざるを得ず、
  評価が壊滅的に下がる。**自動公開運用に入る前に必須**。
- 最小版: 毎日 1 回、出品中の商品について BaseBlu の `product.json` を叩き、
  `variants[*].available` がすべて false なら BUYMA 側を停止。

### 🟡 P5: `app/` 系と `scripts/` 系のデータ分離
- `app/` は SQLite DB（`data/automation.db`）
- `scripts/buyma_auto_listing.py` は CSV（`outputs/reports/*.csv`）+ JSON
- ブランド ID マップ（`data/brands.json`）は共有しているが、商品データは別。
- **対応策**: 長期的には `scripts/` 系を `app/` 系に寄せる。ただし売上が立つまでは
  「動くほうで出す」。焦って統合して両方止めるのは最悪。

### 🟢 P6: 画像加工・BuyManager・Scout 拡張（PHASE3-6）未実装
- 売上が月 5 万を超えてから着手。今は不要。

---

## 5. 今すぐ動かせるフロー（2026-04-16 時点）

### 5-A. 最短経路: 34 列 CSV 生成 → 手動アップロード（★推奨）

Mac 上で:

```bash
cd ~/buyma_automation
git pull origin claude/add-test-flag-HibqE
pip3 install -r requirements.txt

# Step 1: BaseBlu からセール商品を取得
python3 scripts/baseblu_sales_to_csv.py
# → outputs/reports/YYYY-MM-DD_baseblu_sales_products_sorted.csv

# Step 2: BUYMA 取込用 34 列 CSV を生成（低価格帯から）
python3 scripts/generate_buyma_csv.py --max-price 30000 --min-profit 3000 --limit 10
# → outputs/reports/YYYY-MM-DD_buyma_listing.csv

# Step 3: BUYMA の管理画面から上記 CSV を手動アップロード
#   https://www.buyma.com/my/sell/ の CSV 取込機能を使用
```

利点:
- Playwright のセレクタ問題に左右されない
- BUYMA 側で内容を目視確認してから公開できる
- 失敗時のダメージが小さい

### 5-B. 自動出品を試す場合（上級）

Mac 上で:

```bash
# 1 件だけ下書き保存（公開しない）でテスト
python3 scripts/buyma_auto_listing.py --draft --test

# 成功したら複数件・実公開
python3 scripts/buyma_auto_listing.py --from 1
```

注意:
- 実際の BUYMA DOM に合わせてセレクタ再調整が必要な場合あり
- エラーが出たらターミナル出力をチャットに貼り付けて修正依頼

---

## 6. 完了済みタスク（PROFIT_FIRST ベース）

- ✅ タスク 1-1: `app/core/pricing.py` VAT/関税/送料/手数料を反映した統一計算（23 テストパス）
- ✅ タスク 1-2: BaseBlu スクレイパー（`scripts/baseblu_sales_to_csv.py` + `app/scouts/baseblu.py`）
- ✅ タスク 1-4: 重複チェック（`app/governors/rules.py::check_duplicate`）
- ✅ タスク 1-5: BUYMA 34 列 CSV 出力（`app/core/csv_writer.py` + `scripts/generate_buyma_csv.py`）

## 7. 未完了タスク（PROFIT_FIRST ベース）

- ⬜ タスク 1-3: 翻訳 API 接続（DeepL / Google Translate）
- ⬜ タスク 1-6: エンドツーエンド統合テスト（モックデータで `generate_buyma_csv.py` 完走確認）
- ⬜ タスク 2-1: BUYMA 自動出品（セレクタ更新済み、動作検証中）
- ⬜ タスク 2-2: 在庫自動チェック・停止（Guard）
- ⬜ タスク 2-3: 価格追従
- ⬜ タスク 2-4: エラー通知

---

## 8. 次に進めるべきアクション（優先度順）

### 即時（今週）
1. **`generate_buyma_csv.py` で実 CSV を生成し、BUYMA に手動アップロード**
   - これで 2026-04-16 時点の新規実装が実売上につながるかを検証
   - 少なくとも 1 件でも売れれば PROFIT_FIRST フェーズ 1 達成
2. **翻訳 API 接続**（タスク 1-3）
   - Mac の `.env` に `DEEPL_API_KEY` を設定
   - `app/utils/text.translate_description` で DeepL を呼ぶ実装を追加
   - `scripts/generate_buyma_csv.py` で使われるように統合

### 近い将来（初売上後）
3. **Guard（在庫監視）最小実装**（タスク 2-2）
4. **価格計算ロジックの収束**（P3）: `filter_baseblu_profitable.py` を `pricing.py` ベースに書き換え
5. **`scripts/buyma_auto_listing.py` の再検証**: `--draft` で 1 件だけ試す

### 中長期
6. Ranker（PHASE3、競合調査）・Order Desk（PHASE4、注文確定〜カート投入）
7. Scout 拡張（PHASE5、yoox / ssense / farfetch 追加）
8. Reporter（PHASE6、売上ダッシュボード）

---

## 9. 実装・運用時の絶対ルール（CLAUDE.md / PROFIT_FIRST より抜粋）

1. サーバーで外部サイトにアクセスしない（baseblu.com / buyma.com → Mac で実行）
2. ログイン情報・API キーをチャットに出さない（.env / config.json のみ）
3. モックデータで先にテスト、実サイトは Mac で
4. タスク完了ごとに commit & push、完了条件を満たさない限り完了としない
5. `docs/reference/pluselect_source/python_scripts/*.py` は PyArmor 暗号化されているため解析しない

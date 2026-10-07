# BUYMA 出品支援ツール

海外 EC サイト（BaseBlu ほか）のセール商品から「利益が出て BUYMA で売れそうなもの」を選び、
BUYMA の出品フォームにそのまま写せる **出品シート** を作るところまでを自動でやるツールです。
**BUYMA への入力・下書き保存・公開は人が行います**（候補選び・原価計算・シート作成 = ツール / 入力・公開 = 人間）。

> ⚠️ 2026-10-07 方針変更: BUYMA の規約は許可のない外部プログラム・自動出品ツールを禁止しているため
> （[BUYMA ガイド](https://qa.buyma.com/information/news/30118.html)）、BUYMA の画面をブラウザで
> 自動操作するスクリプト（`buyma_auto_listing.py`・相場取得など）は**既定で停止**しました。
> 出品は **出品シートを見ながら通常の出品フォーム（https://www.buyma.com/my/sell/new?tab=b）に手入力** して
> 下書き保存するのが既定です。自動化は公式の **Personal Shopper API**（2026-05-14 に全出品者へ公開・申込制、
> https://specification.personal-shopper-api.buyma.com/ ）の承認後に対応する予定です。
> 一括出品 CSV（`generate_bulk_upload.py`）は **一括出品編集の権限があるアカウント（ショップ等）向け** です。
> 一般の個人アカウントでは https://www.buyma.com/my/sell/bulk/ が「アクセスが許可されていません」になります
> （2026-10-08 確認。BUYMA のショップ出店ガイドでも一括出品機能は一般個人 ×・ショップ ○）。
> 本公開・出品停止・価格更新の自動操作は廃止し、どの設定でも動きません。

当面の目標は「機能を増やす」ことではなく **まず 1 件売る** ことです
（考え方: `docs/strategy/FIRST_SALE_SPRINT.md`）。

---

## 何をしてくれるか（7 工程）

`scripts/run_autopilot.py` を 1 回実行すると、次の順で小さなプログラムが順番に動きます。

| 工程 | 内容 | ネット | 使うファイル |
|---|---|---|---|
| ① 集める | 仕入先のセール商品を一覧にする | 必要 | `baseblu_sales_to_csv.py` / `shopify_sales_to_csv.py` |
| ② 計算する | 送料・関税・手数料を全部足した原価から売値を決め、利益 ¥5,000 未満を落とす | 不要 | `filter_baseblu_profitable.py` |
| ③ 相場を見る | BUYMA で同じ商品がいくらで何件出ているか集める（**既定で停止**。`BUYMA_ALLOW_BROWSER_AUTOMATION=1` の時だけ） | 必要 | `fetch_buyma_market_prices.py` |
| ④ 決め直す | 相場を見て売値を決め直す（多ければ安く、赤字なら見送り） | 不要 | `filter_baseblu_profitable.py --market` |
| ⑤ AI | 日本語の商品名・説明・カテゴリを作り、出品してよいか判定 | API | `ai_enrich_candidates.py` |
| ⑥ 出品シート | 出品フォームの順に「入力する値 / 画面で選ぶ項目」と原価内訳・利益・下限価格・BUYMA 検索 URL をまとめる。BUYMA にはアクセスしない | 不要 | `generate_listing_sheet.py`（候補選びは `select_listing_candidates.py`） |
| ⑦ 入力・公開 | **あなたが** シートを見て通常の出品フォームに入力 →「下書き保存」→ 確認して公開 | — | — |

（一括出品編集の権限があるアカウントだけは、⑥ の代わりに `--bulk-zip N` / `generate_bulk_upload.py` で一括出品 zip も作れます。）

⑤ は `.env` に `ANTHROPIC_API_KEY` が無ければ自動で飛ばされます（週 ¥500 の予算で自動停止）。
⑥ は `--draft N` を付けたときだけ動きます（上位 N 件の出品シート）。毎回の最初に ECB の参照レートを取りに行きます（失敗しても前回値で続行）。

売値の決め方（€200 のバッグの例、ECB 2026-10-06 の 1 € = 178.15 円 × 安全幅 3% = 183.49 円）:
商品代 ¥36,699（baseblu の en-us 価格は既に伊 VAT 抜きなので控除なし）+ 国際送料 ¥9,175 + 関税 ¥3,670
+ 輸入消費税 ¥4,954 + 通関手数料 ¥2,200 + カード手数料 ¥1,009（商品代 + 国際送料の 2.2%）
+ 国内送料 ¥1,000 + 振込手数料 ¥385 = 原価 ¥59,092
→ 25% の利益と BUYMA 手数料 7.7% + 固定手数料 ¥165 を乗せて **売値 ¥80,300**（利益 ¥14,860）。
計算式は `app/core/pricing.py`、為替は `app/core/fx.py`、仕入先ごとの条件は `data/sources.json` にあります。

為替・手数料の設定（環境変数、どれも省略可）:

| 変数 | 既定 | 意味 |
|---|---|---|
| `EUR_TO_JPY` など | なし | 為替を固定する（設定すると ECB の値より優先。**古い値を入れっぱなしにしない**） |
| `FX_BUFFER_PCT` | `0.03` | 為替の安全幅（3%）。カード会社のレートと値動きの分 |
| `FX_MAX_AGE_DAYS` | `7` | ECB キャッシュがこれより古いと警告 |
| `BUYMA_TRANSFER_FEE_JPY` | `385` | 売上の振込手数料（楽天銀行なら 220） |
| `BUYMA_FIXED_FEE_ENABLED` | `1` | BUYMA の成約ごとの固定手数料（¥55〜¥220、2026-10-01 以降・BUYMA 告知 p=95495）を原価に入れる |
| `BUYMA_ALLOW_BROWSER_AUTOMATION` | なし | `1` の時だけ旧ブラウザ自動操作（下書き・相場取得）が動く。規約上のリスクあり、非推奨 |

---

## Mac の準備（最初に 1 回）

インターネットに出る工程（⓪①）は **あなたの Mac でしか動きません**
（Claude Code のクラウドからは baseblu / BUYMA に接続できません）。

```bash
cd ~/buyma_automation
git pull origin claude/add-test-flag-HibqE
pip3 install -r requirements.txt
python3 -m playwright install chromium
```

BUYMA のログイン情報は `config.json.example` をコピーして `config.json` に書きます
（`cp config.json.example config.json` → `buyma_email` / `buyma_password` を入力）。
AI を使う場合は `.env` に `ANTHROPIC_API_KEY=...` を 1 行足します。
**ログイン情報や API キーはチャットに貼らないでください。**

---

## 毎日の使い方（3 コマンド）

```bash
# 練習: ネットも API キーも使わず、モック 5 件で ① 〜 ⑤ を通す
python3 scripts/run_autopilot.py --test

# 本番: ① 集める 〜 ⑤ AI まで
python3 scripts/run_autopilot.py

# 手入力で出す候補を選ぶ（原価 ≤ ¥80,000・利益 ≥ ¥5,000・よく出るサイズの在庫あり・売れやすいブランド優先）
#   --refresh: 上位だけ仕入先の公開ページで在庫・価格・素材を取り直す（2 秒間隔）
python3 scripts/select_listing_candidates.py --source baseblu --limit 5 --refresh

# 上位 3 件の出品シートを作る → outputs/listing_sheets/<日時>/（listing_sheets.html を開く）
python3 scripts/generate_listing_sheet.py --limit 3
#   → 仕入先ページで在庫・価格を確認
#   → https://www.buyma.com/my/sell/new?tab=b にシートの順で入力（🔽 の項目は画面で選ぶ）→「下書き保存する」
#   → 内容を確認して公開
#   → 保存した商品 ID を出品記録に追記（在庫・価格の見張り役の対象になる）:
python3 scripts/generate_listing_sheet.py --record 1=133231149      # シート #1 の商品 ID
python3 scripts/generate_listing_sheet.py --record 2=133231150@78000 # BUYMA で価格を変えたら @価格
```

出品シートの記号: ✏️ 入力（そのまま貼る）/ 🔽 選択（ブランド・カテゴリ・色系統・サイズ・配送方法・地域など、
BUYMA の画面で選ぶ。ID は書いていません）/ ⚠️ 確認（価格・購入期限など本人が決める）/ ℹ️ 参考（原価内訳・検索 URL）。
競合の価格はシートの「BUYMA 検索」URL を開いて目で確認します（ツールは BUYMA の検索結果を取りに行きません）。
ブランドの優先度 `data/brand_demand_tiers.json` は実測ではない暫定の推測です。

一括出品編集の権限があるアカウントの場合だけ: `python3 scripts/run_autopilot.py --skip-scrape --bulk-zip 3`
（または `generate_bulk_upload.py --limit 3`）で zip を作り、https://www.buyma.com/my/sell/bulk/ からアップロード、
`generate_bulk_upload.py --import-ids <ダウンロードした items CSV>` で商品 ID を取り込みます。

出品後の見張り役（どちらも BUYMA には触れず、対応が必要な商品を一覧にするだけ）:

```bash
python3 scripts/check_inventory.py --limit 5        # 仕入先で売り切れた商品・サイズを見つける
python3 scripts/update_listed_prices.py --limit 3   # 仕入値・相場の変化で売値を見直す
python3 scripts/update_listed_prices.py --confirm 123456789=98000  # BUYMA で売価を直したら記録
```

一番簡単なやり方は、Mac で Claude Code を開いて日本語で頼むことです
（例:「run_autopilot.py --test を実行して」）。手順は `docs/MAC_AI_SETUP.md`。

---

## できたファイルの置き場

すべて `outputs/reports/` に日付付きで保存されます。

| ファイル | 中身 |
|---|---|
| `YYYY-MM-DD_<仕入先>_sales_products_sorted.csv` | ① の全セール品 |
| `YYYY-MM-DD_<仕入先>_profitable_products.csv` | ②④⑤ の出品候補（売値・利益・AI の列付き） |
| `YYYY-MM-DD_market_prices.json` | ③ の相場メモ |
| `YYYY-MM-DD_auto_listing_results.csv` | 出品記録（商品 ID・仕入先 URL・出品サイズ）。同じ日の分は追記 |
| `YYYY-MM-DD_<仕入先>_listing_candidates.csv` | 手入力で出す候補（`select_listing_candidates.py`、BUYMA 検索 URL 付き） |
| `outputs/listing_sheets/<日時>/` | ⑥ の出品シート（`listing_sheets.html` / 1 商品 1 枚の `.md` / `.csv` / `sheets_manifest.json`）。gitignore 済み |
| `outputs/bulk/*_buyma_bulk_draft.zip` | 一括出品 zip（権限のあるアカウントのみ） |
| `outputs/bulk/*_buyma_bulk_manifest.json` | zip の商品管理番号 ↔ 仕入先の対応表（`--import-ids` で使う） |

---

## 仕入先を増やす

`data/sources.json` に設定を 1 ブロック足すだけで、Shopify 系のサイトを追加できます（コード不要）。

```bash
python3 scripts/shopify_sales_to_csv.py --list                  # 設定済み一覧
python3 scripts/shopify_sales_to_csv.py --source <名前> --probe # 取得できるか判定 (Mac)
python3 scripts/run_autopilot.py --source <名前>                # その仕入先で全工程
```

確認済みの仕入先は今のところ baseblu だけです。候補の調査: `docs/strategy/SUPPLIER_CANDIDATES_2026-09.md`。

---

## フォルダ構成

```
buyma_automation/
├── scripts/            実行するプログラム (入口は run_autopilot.py)
├── app/core/           計算式 (pricing.py) と仕入先の定義 (sources/)
├── app/ai/             AI の呼び出し (モデルの使い分けは router.py)
├── app/utils/          純粋な変換関数 (Playwright 非依存)
├── data/               設定と対応表 (sources.json / brands.json / categories.json / tags.json)
├── outputs/reports/    生成された CSV / JSON
├── outputs/listing_sheets/  出品シート (手入力用、作成時点の価格。git には入れない)
├── tests/              自動テスト (python3 -m unittest discover -s tests)
└── docs/               設計・戦略メモ
```

---

## 困ったとき

- エラーが出たら、ターミナルの出力をそのまま Claude に貼ってください。
  `python3 scripts/ai_diagnose.py --log <ログファイル>` でも診断できます。
- 一括出品（権限のあるアカウントのみ）のエラー文言は BUYMA の「一括出品編集のエラー文言」（https://buyersinfo.buyma.com/?page_id=79316）。
  列名が合わない場合は、BUYMA からダウンロードした CSV を `--items-template` / `--colorsizes-template` で渡すと列名・並びを合わせます。

## 公式 API（予定）

BUYMA Personal Shopper API は 2026-05-14 に全出品者へ公開されました（申込制・無料・審査あり）。
申込: 仕様サイト https://specification.personal-shopper-api.buyma.com/ の「利用申込書（出品者様用）」。
承認後は BUYMA Partners でアプリを登録（Webhook URL が必須 = 公開 HTTPS の受け口が要る）→ OAuth でトークン取得
→ 商品 API（`control: "draft"` で下書き登録）。このツールの自動化はその後に対応します。問い合わせ: buyer-support@buyma.com

## もっと詳しく

- `HANDOFF.md` — 直近の作業状況と、次にやること（セッションの引き継ぎ）
- `CLAUDE.md` — Claude Code 向けの指示書（開発ルール・落とし穴）
- `docs/strategy/FIRST_SALE_SPRINT.md` — 「まず 1 件売る」計画と判定基準
- `docs/AI_MODEL_POLICY.md` — AI の使い分けと費用

# BUYMA 出品支援ツール

海外 EC サイト（BaseBlu ほか）のセール商品から「利益が出て BUYMA で売れそうなもの」を選び、
BUYMA 公式の **一括出品 CSV（下書き）** を作るところまでを自動でやるツールです。
**アップロードと公開ボタンは人が行います**（CSV 作成 = ツール / アップロード・公開 = 人間）。

> ⚠️ 2026-10-07 方針変更: BUYMA の規約は許可のない外部プログラム・自動出品ツールを禁止しているため
> （[BUYMA ガイド](https://qa.buyma.com/information/news/30118.html)）、BUYMA の画面をブラウザで
> 自動操作するスクリプト（`buyma_auto_listing.py`・相場取得など）は**既定で停止**しました。
> 出品は公式の一括出品編集（https://www.buyma.com/my/sell/bulk/）と、承認後は公式 API を使います。
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
| ⑥ 一括出品 CSV | 公式の一括出品用 zip（items.csv + colorsizes.csv、すべて「下書き」）を作る。BUYMA にはアクセスしない | 不要 | `generate_bulk_upload.py` |
| ⑦ アップロード・公開 | **あなたが** zip を一括出品編集からアップロードし、下書きを確認して公開ボタンを押す | — | — |

⑤ は `.env` に `ANTHROPIC_API_KEY` が無ければ自動で飛ばされます（週 ¥500 の予算で自動停止）。
⑥ は `--draft N` を付けたときだけ動きます。毎回の最初に ECB の参照レートを取りに行きます（失敗しても前回値で続行）。

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

# 上位 3 件の一括出品 zip（下書き）を作る → outputs/bulk/
python3 scripts/run_autopilot.py --skip-scrape --draft 3
#   → https://www.buyma.com/my/sell/bulk/ の「商品リストをアップロードする」で zip を登録（下書きになる）
#   → BUYMA の画面で 1 件ずつ確認して公開
#   → 出品リストをダウンロードして商品 ID を取り込む:
python3 scripts/generate_bulk_upload.py --import-ids ~/Downloads/items.utf8.csv
```

ブランド・カテゴリ・色系統・配送方法・地域の ID は、一括出品編集ページの「ID表を確認する」から
ダウンロードした表を見て `data/buyma_id_tables/*.json` に書きます（書くまでは空欄の下書きになり、
公開前に画面で選びます）。

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
| `outputs/bulk/*_buyma_bulk_draft.zip` | ⑥ の一括出品 zip（下書き） |
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
├── tests/              自動テスト (python3 -m unittest discover -s tests)
└── docs/               設計・戦略メモ
```

---

## 困ったとき

- エラーが出たら、ターミナルの出力をそのまま Claude に貼ってください。
  `python3 scripts/ai_diagnose.py --log <ログファイル>` でも診断できます。
- 一括出品のエラー文言は BUYMA の「一括出品編集のエラー文言」（https://buyersinfo.buyma.com/?page_id=79316）。
  列名が合わない場合は、BUYMA からダウンロードした CSV を `--items-template` / `--colorsizes-template` で渡すと列名・並びを合わせます。

## もっと詳しく

- `HANDOFF.md` — 直近の作業状況と、次にやること（セッションの引き継ぎ）
- `CLAUDE.md` — Claude Code 向けの指示書（開発ルール・落とし穴）
- `docs/strategy/FIRST_SALE_SPRINT.md` — 「まず 1 件売る」計画と判定基準
- `docs/AI_MODEL_POLICY.md` — AI の使い分けと費用

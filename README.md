# BUYMA 出品支援ツール

海外 EC サイト（BaseBlu ほか）のセール商品から「利益が出て BUYMA で売れそうなもの」を選び、
BUYMA に**下書き**として登録するところまでを自動でやるツールです。
**公開ボタンは人が押します**（下書き = ツール / 公開 = 人間）。

当面の目標は「機能を増やす」ことではなく **まず 1 件売る** ことです
（考え方: `docs/strategy/FIRST_SALE_SPRINT.md`）。

---

## 何をしてくれるか（7 工程）

`scripts/run_autopilot.py` を 1 回実行すると、次の順で小さなプログラムが順番に動きます。

| 工程 | 内容 | ネット | 使うファイル |
|---|---|---|---|
| ① 集める | 仕入先のセール商品を一覧にする | 必要 | `baseblu_sales_to_csv.py` / `shopify_sales_to_csv.py` |
| ② 計算する | 送料・関税・手数料を全部足した原価から売値を決め、利益 ¥5,000 未満を落とす | 不要 | `filter_baseblu_profitable.py` |
| ③ 相場を見る | BUYMA で同じ商品がいくらで何件出ているか集める | 必要 | `fetch_buyma_market_prices.py` |
| ④ 決め直す | 相場を見て売値を決め直す（多ければ安く、赤字なら見送り） | 不要 | `filter_baseblu_profitable.py --market` |
| ⑤ AI | 日本語の商品名・説明・カテゴリを作り、出品してよいか判定 | API | `ai_enrich_candidates.py` |
| ⑥ 下書き | BUYMA の出品画面に自動入力して「下書き保存」 | 必要・ログイン | `buyma_auto_listing.py` |
| ⑦ 公開 | **あなたが**下書きを確認して公開ボタンを押す | — | — |

⑤ は `.env` に `ANTHROPIC_API_KEY` が無ければ自動で飛ばされます（週 ¥500 の予算で自動停止）。
⑥ は `--draft N` を付けたときだけ動きます。

売値の決め方（€200 のバッグの例、1 € = 186 円）:
商品代 ¥30,988（現地税の還付後）+ 国際送料 ¥9,300 + 関税 ¥3,223 + 輸入消費税 ¥4,351
+ 通関手数料 ¥2,200 + カード手数料 ¥818 + 国内送料 ¥1,000 + 振込手数料 ¥330 = 原価 ¥52,210
→ 25% の利益と BUYMA 手数料 7.7% を乗せて **売値 ¥70,800**（利益 ¥13,138）。
計算式は `app/core/pricing.py`、仕入先ごとの条件は `data/sources.json` にあります。

---

## Mac の準備（最初に 1 回）

インターネットに出る工程（①③⑥）は **あなたの Mac でしか動きません**
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

# 上位 3 件を BUYMA に下書き保存（ブラウザが開きます。公開は管理画面で手動）
python3 scripts/run_autopilot.py --skip-scrape --skip-market --draft 3
```

出品後の見張り役（どちらもまず `--dry-run` で内容を確認してから）:

```bash
python3 scripts/check_inventory.py --dry-run --limit 5     # 仕入先で売り切れた商品を見つける
python3 scripts/update_listed_prices.py --dry-run --limit 3 # 仕入値・相場の変化で売値を見直す
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
| `YYYY-MM-DD_auto_listing_results.csv` | ⑥ の結果（下書き ID・仕入先 URL） |

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
- ログインできない → `config.json` のメールアドレス・パスワードを確認。
  ログイン状態は `state/buyma_storage_state.json` に保存され、次回から使い回されます。
- BUYMA の出品画面の癖（自動操作の落とし穴）は `CLAUDE.md` の §「BUYMA 出品フォームの仕様」にまとめてあります。

## もっと詳しく

- `HANDOFF.md` — 直近の作業状況と、次にやること（セッションの引き継ぎ）
- `CLAUDE.md` — Claude Code 向けの指示書（開発ルール・落とし穴）
- `docs/strategy/FIRST_SALE_SPRINT.md` — 「まず 1 件売る」計画と判定基準
- `docs/AI_MODEL_POLICY.md` — AI の使い分けと費用

# BUYMA 完全自動化プロジェクト

海外ECサイト（BaseBlu）のセール商品をBUYMAに自動出品するシステムです。

> **2026-09 更新: AI オートパイロット**
> 取得 → 利益計算 → 相場 → AI 補強 (出品文/カテゴリ/審査) → 下書き を 1 コマンドで回せます。
> モデルは用途別に使い分け (Haiku / Sonnet / Fable)、同じ入力は二度課金しません。
>
> ```bash
> python3 scripts/run_autopilot.py --test      # まずモックで通し確認
> python3 scripts/run_autopilot.py             # 実データ (Mac で実行)
> python3 scripts/run_autopilot.py --skip-scrape --skip-market --draft 3   # 上位 3 件を下書き
> ```
> 詳細と費用の目安: `docs/AI_MODEL_POLICY.md`
>
> **仕入先を増やす**: `data/sources.json` に設定を 1 ブロック足すだけで新しい
> Shopify 系サイトを追加できます (コードを書く必要はありません)。
>
> ```bash
> python3 scripts/shopify_sales_to_csv.py --list                  # 設定済み一覧
> python3 scripts/shopify_sales_to_csv.py --source <名前> --probe # 取得できるか判定
> python3 scripts/run_autopilot.py --source <名前>                # 全工程を実行
> ```
> 候補サイトの調査結果: `docs/strategy/SUPPLIER_CANDIDATES_2026-09.md`

---

## フォルダ構成

```
BUYMAオートメーション/
├── scripts/
│   ├── baseblu_sales_to_csv.py       ✅ BaseBluからセール商品データを取得
│   ├── filter_baseblu_profitable.py  ✅ 利益5,000円以上の商品を抽出
│   └── buyma_text_input.py           🔄 BUYMAに商品名・価格を自動入力
├── outputs/
│   └── reports/                      CSVファイルが保存される場所
├── config.json.template              ← これをコピーしてconfig.jsonに名前変更
└── README.md                         このファイル
```

---

## 初回セットアップ（最初に1回だけ実行）

### 1. Python のインストール確認
```
python3 --version
```
Python 3.8以上が必要です。

### 2. 必要なライブラリのインストール
```
pip install requests playwright
playwright install chromium
```

### 3. ログイン情報の設定
`config.json.template` を `config.json` にコピーして、
BUYMAのメールアドレスとパスワードを入力してください。

```json
{
    "buyma_email": "your@email.com",
    "buyma_password": "yourpassword"
}
```

⚠️ `config.json` は絶対に他人に見せないでください。

---

## 毎日の使い方（3ステップ）

### STEP 1: BaseBluからセール商品を取得
```
python3 scripts/baseblu_sales_to_csv.py
```
→ `outputs/reports/YYYY-MM-DD_baseblu_sales_products_sorted.csv` が生成されます

### STEP 2: 利益が出る商品を絞り込む
```
python3 scripts/filter_baseblu_profitable.py
```
→ `outputs/reports/YYYY-MM-DD_baseblu_profitable_products.csv` が生成されます
→ 推定利益5,000円以上の商品のみ抽出されます

### STEP 3: BUYMAに自動入力（テスト）
まず1件だけテスト実行してフォームへの入力が正しいか確認してください：
```
python3 scripts/buyma_text_input.py --test
```

問題なければ全件実行：
```
python3 scripts/buyma_text_input.py
```
→ BUYMAの出品フォームに商品名・価格・説明文が自動入力されます
→ 画像は手動で後から追加してください
→ 処理結果は `outputs/reports/YYYY-MM-DD_buyma_listing_results.csv` に保存されます

---

## 現在の自動化レベル

| 工程 | 状態 | 方法 |
|------|------|------|
| BaseBlu商品データ取得 | ✅ 完成 | baseblu_sales_to_csv.py |
| 利益計算・候補抽出 | ✅ 完成 | filter_baseblu_profitable.py |
| BUYMAにテキスト・価格入力 | ✅ 完成 | buyma_text_input.py |
| BUYMAに画像アップロード | ⚠️ 未解決 | ボット検知対策が必要（後日対応） |
| 出品完了確認・通知 | 🔄 未実装 | 画像解決後に対応 |

---

## 画像アップロードについて（現状）

BUYMAのBot検知が強力なため、画像の自動アップロードはまだ実装できていません。
現在の回避策：

1. **手動で後から追加**: BUYMA管理画面の「下書き」一覧から、
   自動入力済みの商品に画像だけ手動で追加してください。

2. **今後の対応予定**:
   - Coworkのブラウザ録画機能で人間の操作を学習させる（最優先）
   - BUYMAの公式APIが画像URLに対応しているか問い合わせる

---

## トラブルシューティング

**「下書き保存ボタンが見つかりません」と表示される場合**
→ BUYMAのフォームデザインが変更された可能性があります。
  Claudeに「BUYMAの出品フォームを確認してセレクタを更新して」と依頼してください。

**ログインできない場合**
→ config.json のメールアドレスとパスワードを確認してください。
→ BUYMAで2段階認証を設定している場合は、一時的に無効にしてください。

**「playwright がインストールされていません」と表示される場合**
→ `pip install playwright` と `playwright install chromium` を実行してください。

# BUYMA Auto Lister Chrome 拡張

BaseBlu からセール商品を取得し、BUYMA へ自動出品する補助を行う Chrome 拡張機能です。
ブラウザ内で直接動作するため、サーバー不要・ネットワーク制限なしで使えます。

## 機能

- baseblu.com の商品詳細ページから商品情報を 1 クリックで取得
- baseblu.com の一覧ページから複数商品を一括取得（裏タブで順次処理）
- 利益計算・Governor 判定（承認 / 保留 / NG）
- 日本語タイトル・商品説明の自動生成
- BUYMA の出品フォームへ自動入力（下書き / 公開出品）
- 全データは `chrome.storage.local` に保存（ローカル完結）

## インストール手順

1. Chrome を開き、アドレスバーに `chrome://extensions/` を入力
2. 画面右上の **「デベロッパー モード」** を ON
3. **「パッケージ化されていない拡張機能を読み込む」** をクリック
4. このリポジトリの `extension/` フォルダを選択
5. ツールバーに BUYMA Auto Lister のアイコンが表示されれば成功

## 使い方

### 1. 初期設定

拡張アイコン → 「設定」タブで以下を入力：

- **為替レート (EUR→JPY)**: 例 163.0
- **目標利益率**: 例 25 (%)
- **最低利益額**: 例 3000 (円)
- **国際配送料**: 例 30 (EUR)
- **BUYMA 手数料率**: 0.058 (5.8%)

### 2. 商品取得

**パターン A: 1 件ずつ**
1. baseblu.com の商品詳細ページを開く
2. 拡張アイコン → 「取得」タブ → 「現在のページを取得」
3. 「商品」タブに結果が表示される

**パターン B: 一覧から一括**
1. baseblu.com のセール一覧ページを開く
2. 拡張アイコン → 「取得」タブ → 「一覧から一括取得」
3. 裏タブで 1 件ずつ処理されるので、完了するまで待機

### 3. BUYMA 出品

「商品」タブに取得結果が並ぶ。承認（approved）判定が出た商品で：

- **BUYMA下書き**: 出品フォームを開き自動入力 → 下書き保存
- **出品**: 出品フォームを開き自動入力 → 公開

※ 初回はフォームの見え方を手動確認することを強く推奨。

## アーキテクチャ

```
extension/
├── manifest.json           # Manifest V3 定義
├── popup/                  # ツールバー アイコンのポップアップ
│   ├── popup.html
│   ├── popup.css
│   └── popup.js
├── background/
│   └── service_worker.js   # タブ制御・コンテンツスクリプト間の橋渡し
├── content/
│   ├── baseblu.js          # baseblu.com でのスクレイピング
│   └── buyma.js            # buyma.com での自動入力
├── lib/
│   ├── config.js           # 設定管理
│   ├── storage.js          # chrome.storage.local ラッパ
│   ├── profit.js           # 利益計算（Python 版の移植）
│   ├── governor.js         # 出品可否判定
│   └── translator.js       # 日本語化（ブランド・カテゴリ）
├── data/
│   ├── brands.json         # ブランド名 → 日本語
│   └── categories.json     # カテゴリ → 日本語
└── icons/
    └── icon{16,48,128}.png
```

## 既知の調整ポイント

### BUYMA フォームのセレクタ

`content/buyma.js` 冒頭の `SELECTORS` 定数に、フォーム項目の CSS セレクタ候補を
複数列挙してある。実際の BUYMA 出品フォームの DOM 構造に合わせて以下を調整する：

- `title` / `brand` / `category` / `price` / `color` / `description`
- `imageInput` (ファイル input)
- `submitDraft` / `submitPublish` ボタン

セレクタを変更しても拡張のリロード（`chrome://extensions` のリロードボタン）だけで反映される。

### 出品フォーム URL

`background/service_worker.js` の `BUYMA_LISTING_URL` を実際の URL に合わせる：

```js
const BUYMA_LISTING_URL = "https://www.buyma.com/my/sell/new";
```

### 画像アップロード

BUYMA の `input[type="file"]` に `DataTransfer` 経由で File を注入する実装になっている。
BUYMA 側の実装（React Dropzone 等）によってはイベント発火だけでは受理されない場合がある。
その際は手動で画像をドロップしてもらう運用に切り替える。

## 開発メモ

- 本拡張は **ローカル完結**。外部サーバーにデータを送らない。
- 認証情報は BUYMA のログインセッションをブラウザ側で使う。拡張にパスワードは保存しない。
- Python 版 (`scripts/run_pipeline.py`) の利益計算・Governor ロジックを JavaScript に直訳している。
  仕様変更時は両方を揃えること。

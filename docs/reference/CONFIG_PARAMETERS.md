# PLUSELECT 設定項目リファレンス

PLUSELECT_TOOL の `.env` から抽出した、BUYMA 自動化に必要な設定項目一覧です。
`config.json` の設計や、UI の入力項目を作るときの参考にしてください。

## 1. スクレイパー（商品リスト自動作成）関連

| 項目名 | 日本語 | 説明 |
|--------|--------|------|
| sex | 性別 | レディース / メンズ / キッズ |
| nocategory | 除外カテゴリ | 取得しないカテゴリ |
| translate_name | 商品名翻訳 | 英語→日本語の機械翻訳ON/OFF |
| nobrand | 除外ブランド | 取得しないブランド |
| no_ban_brand | 禁止ブランド除外 | BUYMA で禁止されているブランドを除外 |
| currency | 通貨 | EUR / USD / GBP など |
| max_page | 最大ページ数 | スクレイピングの上限ページ |
| csv_prm | CSV パラメータ | 出力CSVの書式 |
| edit_name | 商品名編集 | 商品名のテンプレート |
| max_price | 最高価格 | この金額を超える商品は除外 |
| vatoff_late | VAT還付率 | 欧州：16.7% 前後 |
| vip_late | VIP割引率 | 会員割引率 |
| delivery_price | 配送料 | 国際送料 |
| profit_late | 利益率 | 目標利益率（例：20%） |
| duty | 関税 | 関税計算設定 |
| duty_pattern | 関税パターン | カテゴリ別の税率設定 |
| size_variation | サイズバリエーション | サイズ展開の扱い |
| buyplace | 買付地 | 商品の買付国 |
| sendplace | 発送地 | 発送元の国 |
| buyma_shop | BUYMA ショップ名 | 自分のショップ表示名 |
| tag | タグ | 商品に付けるハッシュタグ |
| thema | テーマ | 商品テーマ分類 |
| season | シーズン | 2024SS など |
| delivery | 配送方法 | DHL / FedEx など |
| deadline | 発送期限 | 発送までの日数 |
| stock | 在庫 | 在庫数 |
| memo | メモ | 内部管理メモ |

## 2. 画像加工ツール関連

| 項目名 | 説明 |
|--------|------|
| edit_mode | 編集モード（テスト/全て/透過/ロゴのみ） |
| master_dir | マスター画像フォルダ |
| choiced_dir | 選択画像フォルダ |
| scriptPath | スクリプトパス |
| logo_size | ロゴサイズ |
| item_name | 商品名表示 |
| item_size | 商品サイズ表示 |
| item_move_x, item_move_y | 商品画像の位置調整 |
| bg_size | 背景サイズ |
| back_move_x, back_move_y | 背景の位置調整 |
| logo_move_x, logo_move_y | ロゴの位置調整 |
| bg_num | 背景番号 |
| bg_image | 背景画像 |
| img_effect | 画像エフェクト |
| img_frame | フレーム |
| img_logo | ロゴ |
| image_diff | 画像差分 |
| addimg_1_name, addimg_1_size, addimg_1_x, addimg_1_y | 追加画像1の設定 |
| addimg_2_*, addimg_3_* | 追加画像2, 3 |
| electron_dir | Electronディレクトリ |

## 3. BuyManager（出品後管理）関連

| 項目名 | 説明 |
|--------|------|
| days | 集計対象日数 |
| access_prm | アクセス数の閾値 |
| want_prm | ほしいもの登録数の閾値 |
| cart_prm | カート追加数の閾値 |
| price_prm | 価格調整パラメータ |
| maxprice_prm | 最高価格パラメータ |
| date_prm | 日付パラメータ |

## 4. 出品ツール関連

| 項目名 | 説明 |
|--------|------|
| day_score | 日スコア（出品スケジュール） |
| hour_score | 時スコア |
| cookie | BUYMAセッション cookie |
| draft | 下書き出品フラグ（ON/OFF） |
| url_memo | URL メモ |
| csv_memo | CSV メモ |
| duplicate | 重複チェック（ON/OFF） |
| wait_time | 出品間隔の待機時間 |

## 5. 共通設定

| 項目名 | 説明 |
|--------|------|
| edit_mode | 編集モード |
| master_dir | マスターフォルダ |
| choiced_dir | 選択フォルダ |
| MODE | 動作モード（dev / pro） |

## 元データ

- ソース：`docs/reference/pluselect_source/env_config_raw.txt`

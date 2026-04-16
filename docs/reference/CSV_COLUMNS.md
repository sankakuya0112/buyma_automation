# BUYMA 取り込み用 CSV：34列仕様

PLUSELECT_TOOL から抽出した BUYMA 自動出品用 CSV フォーマットです。
この順番・名前のまま使えば、BUYMA の取り込み機能にそのまま読ませられます。

## 列定義（全34列）

| # | 列名 | 説明 | 例 |
|---|------|------|-----|
| 1 | item_img_folder | 商品画像が入ったフォルダ名 | `item_00001` |
| 2 | item_name | 商品名（日本語） | `グッチ GGマーモント ショルダーバッグ` |
| 3 | item_brand | ブランド名 | `GUCCI` |
| 4 | item_model | 型番・モデル名 | `443497 DTDID 1000` |
| 5 | item_category | BUYMA カテゴリ | `バッグ > ショルダーバッグ` |
| 6 | item_comment | 商品説明・コメント（日本語） | `人気のGGマーモントシリーズ...` |
| 7 | item_size_color | サイズ・色の一覧 | `BLACK/FREE,RED/FREE` |
| 8 | item_deadline | 発送までの目安 | `7-14日` |
| 9 | item_url | 仕入れ先の商品URL | `https://www.baseblu.com/...` |
| 10 | item_buyplace | 買付地（仕入国） | `イタリア` |
| 11 | item_shop | 買付店舗名 | `BASEBLU` |
| 12 | item_sendplace | 発送地 | `イタリア` |
| 13 | item_announce | 取引について（定型アナウンス） | `ご購入後のキャンセルはお受けできません...` |
| 14 | color | 色（単一） | `BLACK` |
| 15 | size | サイズ（単一） | `FREE` |
| 16 | item_season | シーズン | `2024SS` |
| 17 | item_tag | タグ（ハッシュタグ的な検索キーワード） | `#GUCCI #バッグ #新作` |
| 18 | item_thema | テーマ | `レディース` |
| 19 | item_sell_price | 販売価格（日本円） | `180000` |
| 20 | item_pub_price | 参考上代（希望小売価格） | `220000` |
| 21 | item_delivery | 配送方法 | `DHL` |
| 22 | item_stock | 在庫数 | `3` |
| 23 | item_sku | SKU コード | `GG-MARM-001` |
| 24 | item_duty | 関税の負担区分 | `バイヤー負担` or `バイヤー負担なし` |
| 25 | item_memo | 内部メモ（管理用） | `仕入値 1200EUR` |
| 26 | item_price | 仕入値（現地通貨） | `1200` |
| 27 | item_currency | 仕入通貨 | `EUR` |
| 28 | item_no_cur_price | 仕入値（通貨記号なし数値のみ） | `1200` |
| 29 | item_deli_price | 国際送料 | `5000` |
| 30 | item_vatoff | VAT還付額 | `200` |
| 31 | item_profit | 利益額 | `36000` |
| 32 | item_keywords | SEO キーワード | `グッチ バッグ 新作` |
| 33 | item_topic | トピック | `セール` |
| 34 | item_image | 画像URL（複数は区切り文字で連結） | `https://.../1.jpg\|https://.../2.jpg` |

## 注意事項

- **文字コード**：UTF-8 with BOM
- **区切り文字**：カンマ
- **画像URL の複数指定**：`|`（パイプ）で区切る
- **改行コード**：CRLF 推奨（BUYMA 側の仕様）
- **カラム順序**：この順番通りにすること（BUYMA 取り込み時の期待順）

## 元データ

- ソース：`docs/reference/pluselect_source/csv_columns_raw.txt`
- PLUSELECT_TOOL が実運用で使っていた 2021 年時点のフォーマット
- BUYMA 側の仕様が更新されている可能性があるため、出品テスト時に要検証

"""
BUYMA 取込用 34 列 CSV ライタ。

PROFIT_FIRST タスク 1-5 の実装。PLUSELECT_TOOL が実運用で使用していた
BUYMA 標準フォーマットに準拠する（`docs/reference/CSV_COLUMNS.md` 参照）。

仕様:
    - UTF-8 with BOM
    - 改行コード: CRLF
    - 画像 URL は `|` 区切りで最大 5 枚
    - 列順序は BUYMA_CSV_COLUMNS の通り（変更不可）

使用例:
    from app.core.csv_writer import BuymaListingRow, write_buyma_csv

    row = BuymaListingRow(
        item_name="GUCCI GG マーモント",
        item_brand="GUCCI",
        item_sell_price="180000",
        ...
    )
    write_buyma_csv([row], "outputs/reports/buyma_listing.csv")
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

# BUYMA 取込 CSV の 34 列（順序・名前は変更不可）
BUYMA_CSV_COLUMNS: list[str] = [
    "item_img_folder",
    "item_name",
    "item_brand",
    "item_model",
    "item_category",
    "item_comment",
    "item_size_color",
    "item_deadline",
    "item_url",
    "item_buyplace",
    "item_shop",
    "item_sendplace",
    "item_announce",
    "color",
    "size",
    "item_season",
    "item_tag",
    "item_thema",
    "item_sell_price",
    "item_pub_price",
    "item_delivery",
    "item_stock",
    "item_sku",
    "item_duty",
    "item_memo",
    "item_price",
    "item_currency",
    "item_no_cur_price",
    "item_deli_price",
    "item_vatoff",
    "item_profit",
    "item_keywords",
    "item_topic",
    "item_image",
]

# 定型アナウンス（取引について）
DEFAULT_ANNOUNCE = (
    "◆ご注文前に必ず在庫確認のお問い合わせをお願いいたします。\n"
    "◆海外買付のため、ご注文後のキャンセル・返品はお受けできません。\n"
    "◆関税・消費税は当方で負担いたします。\n"
    "◆お届けまでに 10〜21 日程度お時間をいただきます。\n"
    "◆モニター環境により実物と色味が異なる場合がございます。"
)


@dataclass
class BuymaListingRow:
    """BUYMA 取込 CSV の 1 行分。未指定フィールドは空文字。"""

    item_img_folder: str = ""
    item_name: str = ""
    item_brand: str = ""
    item_model: str = ""
    item_category: str = ""
    item_comment: str = ""
    item_size_color: str = ""
    item_deadline: str = "7-14日"
    item_url: str = ""
    item_buyplace: str = "イタリア"
    item_shop: str = ""
    item_sendplace: str = "イタリア"
    item_announce: str = DEFAULT_ANNOUNCE
    color: str = ""
    size: str = "FREE"
    item_season: str = ""
    item_tag: str = ""
    item_thema: str = "レディース"
    item_sell_price: str = ""
    item_pub_price: str = ""
    item_delivery: str = "DHL"
    item_stock: str = "1"
    item_sku: str = ""
    item_duty: str = "バイヤー負担なし"
    item_memo: str = ""
    item_price: str = ""
    item_currency: str = "EUR"
    item_no_cur_price: str = ""
    item_deli_price: str = ""
    item_vatoff: str = ""
    item_profit: str = ""
    item_keywords: str = ""
    item_topic: str = ""
    item_image: str = ""

    def to_dict(self) -> dict[str, str]:
        """全フィールドを str に揃えた dict を返す。"""
        d = asdict(self)
        return {k: ("" if v is None else str(v)) for k, v in d.items()}


def write_buyma_csv(
    rows: Iterable[BuymaListingRow],
    output_path: str | Path,
) -> int:
    """
    34 列 CSV を書き出す。UTF-8 BOM + CRLF。

    Args:
        rows: BuymaListingRow のイテラブル
        output_path: 出力ファイルパス

    Returns:
        書き出した行数
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    # UTF-8 BOM は encoding="utf-8-sig" で付与、CRLF は lineterminator で指定
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=BUYMA_CSV_COLUMNS,
            lineterminator="\r\n",
        )
        writer.writeheader()
        for row in rows:
            d = row.to_dict()
            # 列順序を必ず BUYMA_CSV_COLUMNS に揃える
            writer.writerow({col: d.get(col, "") for col in BUYMA_CSV_COLUMNS})
            count += 1

    return count


def join_images(image_urls: list[str], max_images: int = 5) -> str:
    """画像 URL リストを BUYMA 形式（`|` 区切り）に連結する。"""
    valid = [u.strip() for u in image_urls if u and u.strip()]
    return "|".join(valid[:max_images])

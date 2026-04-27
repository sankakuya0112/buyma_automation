"""Baseblu 仕入先アダプタ。

メタデータ (EUR / IT / DDU) を保持する薄いラッパ。スクレイピング本体は
scripts/baseblu_sales_to_csv.py の関数群が引き続き担当する (helper 移動は scope 外)。

将来 fetch_products() 実装時は scripts/baseblu_sales_to_csv.py:fetch_all_products
と parse_product を呼んで dict を yield する形にする。
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.core.sources.base import BaseSource


class BasebluSource(BaseSource):
    name = "baseblu"
    currency = "EUR"
    country = "IT"
    landed_cost_basis = "DDU"

    def __init__(self, fetch_details: bool = True) -> None:
        self.fetch_details = fetch_details

    def fetch_products(self, limit: Optional[int] = None) -> Iterable[dict]:
        """Baseblu の Shopify JSON API からセール商品を取得して dict を yield。

        scripts/baseblu_sales_to_csv.py の fetch_all_products + parse_product を
        利用するため、サブプロセスや importlib 経由のロードが必要。Phase 2c の
        スコープでは未実装とし、既存スクリプトを直接呼び出す運用を継続する。
        実装は Italist など他 source 追加時に合わせて行う。
        """
        raise NotImplementedError(
            "BasebluSource.fetch_products は Phase 2c 範囲外。"
            "現状は scripts/baseblu_sales_to_csv.py を直接実行してください。"
        )

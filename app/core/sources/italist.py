"""Italist 仕入先アダプタ。

Italist は Shopify storefront の products.json で公開商品情報を取得できる。
チェックアウト/カート/アカウント領域には触れず、公開 collection の商品 JSON だけを
低頻度で取得する前提。
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.core.sources.base import BaseSource


class ItalistSource(BaseSource):
    name = "italist"
    # products.json は現状 USD 表示。JPY 表示の導入は別途検証する。
    currency = "USD"
    country = "IT"
    # 日本向けの関税込み表示を前提に DDP として計算（二重課税を避ける）。
    landed_cost_basis = "DDP"

    def fetch_products(self, limit: Optional[int] = None) -> Iterable[dict]:
        raise NotImplementedError(
            "ItalistSource.fetch_products は scripts/italist_sales_to_csv.py を使用してください。"
        )

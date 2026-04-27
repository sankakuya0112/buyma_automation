"""仕入先 (Source) 抽象基底クラス。

`app.scouts.BaseScraper` がサイト固有のスクレイピング責務 (DB 書き込み、Playwright 等)
を持つのに対し、`BaseSource` は仕入先のメタデータと CSV パイプライン用のアダプタを
定義する。Phase 2c で BasebluSource / ItalistSource を切り出すための足場。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Iterable, Literal, Optional

if TYPE_CHECKING:
    from app.core.pricing import PricingParams


LandedCostBasis = Literal["DDP", "DDU"]


class BaseSource(ABC):
    """すべての仕入先が継承する抽象基底クラス。

    メタデータ (name / currency / country / landed_cost_basis) はクラス変数として宣言する。
    具象クラスは fetch_products を実装する。
    """

    name: str = ""
    currency: str = ""
    country: str = ""
    landed_cost_basis: LandedCostBasis = "DDU"

    @abstractmethod
    def fetch_products(self, limit: Optional[int] = None) -> Iterable[dict]:
        """セール商品 dict をストリーミング返却する。

        各 dict のスキーマは scripts/baseblu_sales_to_csv.py:parse_product の戻り値に揃える:
            title, vendor, product_type, sku, color, sizes, available_sizes,
            season, sale_price (現地通貨), original_price, discount_rate,
            available, description_en, image_url, sub_images, product_url
        """

    def get_pricing_params(
        self,
        sale_price: float,
        category: str = "",
    ) -> "PricingParams":
        """source の currency / landed_cost_basis を反映した PricingParams を返す。

        filter スクリプトから「source_name 列 → BaseSource → PricingParams」の流れで
        landed_cost_basis ハードコードを解消するために使う。
        """
        from app.core.pricing import PricingParams

        return PricingParams(
            source_price=sale_price,
            currency=self.currency,
            category=category,
            landed_cost_basis=self.landed_cost_basis,
        )

    def metadata_dict(self) -> dict:
        """CSV 行末尾に付ける source 系メタ列の dict。"""
        return {
            "source_name": self.name,
            "currency": self.currency,
            "landed_cost_basis": self.landed_cost_basis,
        }

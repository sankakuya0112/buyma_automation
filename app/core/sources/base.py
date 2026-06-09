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

    # --- 実コストモデル (Phase 2d) ---
    # VAT 還付率。仕入先が輸出価格として VAT を既に控除している場合は 0.0 に
    # すること (二重控除 = 利益過大評価 = 赤字出品リスク)。
    vat_refund_rate: float = 0.167
    # 海外カード決済の事務手数料 (Visa/Master 標準 ~2.2%)。JPY 建て仕入れなら 0。
    purchase_fx_fee_rate: float = 0.022
    # 国内発送費 (出品者→購入者)。宅急便コンパクト〜宅急便 60-80 サイズ想定。
    domestic_shipping_jpy: float = 1000.0

    @abstractmethod
    def fetch_products(self, limit: Optional[int] = None) -> Iterable[dict]:
        """セール商品 dict をストリーミング返却する。

        各 dict のスキーマは scripts/baseblu_sales_to_csv.py:parse_product の戻り値に揃える:
            title, vendor, product_type, sku, color, sizes, available_sizes,
            season, sale_price (現地通貨), original_price, discount_rate,
            available, description_en, image_url, sub_images, product_url
        """

    def shipping_cost_local(self, sale_price: float) -> Optional[float]:
        """仕入先→日本の国際送料 (現地通貨)。

        None を返すと calculate_pricing 側の重量ベース推定 (weight × ¥3,000/kg)
        にフォールバックする。実際の送料体系 (固定額/無料閾値) が分かっている
        source は必ず override すること。重量モデルは低額商品で送料を大幅に
        過小評価する (例: baseblu 実費 €50 ≈ ¥9,300 vs 財布 0.3kg 推定 ¥900)。
        """
        return None

    def get_pricing_params(
        self,
        sale_price: float,
        category: str = "",
    ) -> "PricingParams":
        """source の currency / landed_cost_basis / 実コストを反映した PricingParams を返す。

        filter スクリプトから「source_name 列 → BaseSource → PricingParams」の流れで
        landed_cost_basis ハードコードを解消するために使う。
        """
        from app.core.pricing import PricingParams, resolve_exchange_rate

        shipping_jpy: Optional[float] = None
        shipping_local = self.shipping_cost_local(sale_price)
        if shipping_local is not None:
            shipping_jpy = shipping_local * resolve_exchange_rate(self.currency)

        return PricingParams(
            source_price=sale_price,
            currency=self.currency,
            category=category,
            landed_cost_basis=self.landed_cost_basis,
            vat_refund_rate=self.vat_refund_rate,
            shipping_jpy=shipping_jpy,
            purchase_fx_fee_rate=self.purchase_fx_fee_rate,
            domestic_shipping_jpy=self.domestic_shipping_jpy,
        )

    def metadata_dict(self) -> dict:
        """CSV 行末尾に付ける source 系メタ列の dict。"""
        return {
            "source_name": self.name,
            "currency": self.currency,
            "landed_cost_basis": self.landed_cost_basis,
        }

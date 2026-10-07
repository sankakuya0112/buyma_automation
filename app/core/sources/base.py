"""仕入先 (Source) 抽象基底クラス。

`BaseSource` は仕入先のメタデータ (通貨 / DDP・DDU / VAT 還付 / 送料 / 実コスト) と
CSV パイプライン用のアダプタを定義する。スクレイピング本体は scripts/ 側が担当する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Iterable, Literal, Optional

if TYPE_CHECKING:
    from app.core.pricing import PricingParams


LandedCostBasis = Literal["DDP", "DDU"]

VAT_TREATMENTS = ("none", "deducted_at_checkout")


def resolve_vat_refund_rate(vat_treatment: str, local_vat_rate: float) -> float:
    """vat_treatment + 現地 VAT 率 → 原価計算の VAT 控除率。不正値は ValueError。"""
    from app.core.pricing import vat_extraction_rate

    treatment = (vat_treatment or "none").strip().lower()
    if treatment not in VAT_TREATMENTS:
        raise ValueError(f"vat_treatment は {'/'.join(VAT_TREATMENTS)} のいずれか: {vat_treatment!r}")
    if treatment == "none":
        return 0.0
    if not 0.0 < float(local_vat_rate) < 0.5:
        raise ValueError(f"deducted_at_checkout には local_vat_rate (例 0.22) が必要です: {local_vat_rate!r}")
    return vat_extraction_rate(float(local_vat_rate))


class BaseSource(ABC):
    """すべての仕入先が継承する抽象基底クラス。

    メタデータ (name / currency / country / landed_cost_basis) はクラス変数として宣言する。
    具象クラスは fetch_products を実装する。
    """

    name: str = ""
    currency: str = ""
    country: str = ""
    landed_cost_basis: LandedCostBasis = "DDU"

    # --- 現地 VAT の扱い (2026-10 明示化) ---
    # vat_treatment:
    #   "none"                 … 取得する表示価格 = 日本向けに請求される商品代 (VAT 抜き表示 or
    #                            日本向けでも VAT が外れない)。控除しない。不明なときもこれ (安全側)
    #   "deducted_at_checkout" … 表示価格は現地 VAT 込みで、日本向けの会計で VAT が外れる。
    #                            控除率 = local_vat_rate / (1 + local_vat_rate) (22% → 0.1803)
    # 以前は一律 0.167 を引いており、VAT 抜き価格 (baseblu の en-us 表示) では二重控除、
    # 22% の国の VAT 込み価格では控除不足になっていた。
    vat_treatment: str = "none"
    local_vat_rate: float = 0.0
    # 海外カード決済の事務手数料 (Visa/Master 標準 ~2.2%)。JPY 建て仕入れなら 0。
    purchase_fx_fee_rate: float = 0.022
    # 国内発送費 (出品者→購入者)。宅急便コンパクト〜宅急便 60-80 サイズ想定。
    domestic_shipping_jpy: float = 1000.0
    # 通関の立替手数料 = max(最低額, 率 × (関税 + 輸入消費税))。DDU 仕入れのときだけ掛かる
    # (DDP は関税 0 なので自動的に 0)。DHL 日本 2026 料金表・受取人払い (アカウントなし):
    # 税込 2,200 円 または 立替額の 2% の高い方。
    # ※ 3,300 円は「現地税金元払い (発送人払い)」の料金で、受取人払いには当たらない。
    customs_handling_min_jpy: float = 2200.0
    customs_handling_rate: float = 0.02

    @property
    def vat_refund_rate(self) -> float:
        """原価計算に使う VAT 控除率 (vat_treatment と local_vat_rate から決まる)。"""
        return resolve_vat_refund_rate(self.vat_treatment, self.local_vat_rate)

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
        title: str = "",
    ) -> "PricingParams":
        """source の currency / landed_cost_basis / 実コストを反映した PricingParams を返す。

        filter スクリプトから「source_name 列 → BaseSource → PricingParams」の流れで
        landed_cost_basis ハードコードを解消するために使う。
        title は靴が革か布かの判定 (関税率) に使う。
        """
        from app.core import fx
        from app.core.pricing import PricingParams

        # 為替は「手動指定 or ECB キャッシュ or 固定値」× 安全バッファ (app/core/fx.py)。
        # 送料の円換算と商品代の円換算で同じレートを使うため、ここで明示的に決める。
        exchange_rate = fx.effective_rate(self.currency)

        shipping_jpy: Optional[float] = None
        shipping_local = self.shipping_cost_local(sale_price)
        if shipping_local is not None:
            shipping_jpy = shipping_local * exchange_rate

        return PricingParams(
            source_price=sale_price,
            currency=self.currency,
            exchange_rate=exchange_rate,
            category=category,
            landed_cost_basis=self.landed_cost_basis,
            vat_refund_rate=self.vat_refund_rate,
            shipping_jpy=shipping_jpy,
            purchase_fx_fee_rate=self.purchase_fx_fee_rate,
            domestic_shipping_jpy=self.domestic_shipping_jpy,
            title=title,
            customs_handling_min_jpy=self.customs_handling_min_jpy,
            customs_handling_rate=self.customs_handling_rate,
        )

    def metadata_dict(self) -> dict:
        """CSV 行末尾に付ける source 系メタ列の dict。"""
        return {
            "source_name": self.name,
            "currency": self.currency,
            "landed_cost_basis": self.landed_cost_basis,
        }

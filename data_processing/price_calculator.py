"""価格計算・利益率ロジック"""

import logging
import math

from config import BUYMA_COMMISSION_RATE, EUR_TO_JPY, MIN_PROFIT_RATE, SHIPPING_COST_EUR

logger = logging.getLogger(__name__)


class PriceCalculator:
    """BUYMA出品価格の計算を行うクラス"""

    def __init__(
        self,
        eur_to_jpy: float | None = None,
        commission_rate: float | None = None,
        shipping_eur: float | None = None,
        min_profit_rate: float | None = None,
    ):
        self.eur_to_jpy = eur_to_jpy or EUR_TO_JPY
        self.commission_rate = commission_rate or BUYMA_COMMISSION_RATE
        self.shipping_eur = shipping_eur or SHIPPING_COST_EUR
        self.min_profit_rate = min_profit_rate or MIN_PROFIT_RATE

    def parse_price_eur(self, price_str: str) -> float:
        """EUR価格文字列をfloatに変換する"""
        cleaned = price_str.replace("€", "").replace(",", ".").replace(" ", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            logger.warning("Could not parse price: %s", price_str)
            return 0.0

    def calculate_cost_jpy(self, sale_price_eur: float) -> float:
        """仕入原価（JPY）を計算する（送料込み）"""
        total_eur = sale_price_eur + self.shipping_eur
        return total_eur * self.eur_to_jpy

    def calculate_selling_price(self, sale_price_eur: float) -> dict:
        """販売価格・利益を計算する

        Returns:
            dict: cost_jpy, selling_price_jpy, profit_jpy, profit_rate を含む辞書
        """
        cost_jpy = self.calculate_cost_jpy(sale_price_eur)

        # 最低利益率を確保する販売価格
        # selling * (1 - commission) = cost * (1 + min_profit_rate)
        # selling = cost * (1 + min_profit_rate) / (1 - commission)
        target = cost_jpy * (1 + self.min_profit_rate) / (1 - self.commission_rate)

        # 100円単位に切り上げ
        selling_price_jpy = math.ceil(target / 100) * 100

        # 実際の利益計算
        revenue_after_commission = selling_price_jpy * (1 - self.commission_rate)
        profit_jpy = revenue_after_commission - cost_jpy
        profit_rate = profit_jpy / cost_jpy if cost_jpy > 0 else 0.0

        return {
            "cost_jpy": round(cost_jpy),
            "selling_price_jpy": selling_price_jpy,
            "profit_jpy": round(profit_jpy),
            "profit_rate": round(profit_rate, 4),
        }

    def enrich_product_with_price(self, product: dict) -> dict:
        """商品辞書に価格情報を追加する"""
        sale_price_str = product.get("sale_price_eur", "0")
        sale_price_eur = self.parse_price_eur(sale_price_str)

        if sale_price_eur <= 0:
            logger.warning("Invalid sale price for product: %s", product.get("name", ""))
            return product

        price_info = self.calculate_selling_price(sale_price_eur)
        product["price_jpy"] = price_info["selling_price_jpy"]
        product["profit_jpy"] = price_info["profit_jpy"]
        product["profit_rate"] = price_info["profit_rate"]
        product["cost_jpy"] = price_info["cost_jpy"]
        return product

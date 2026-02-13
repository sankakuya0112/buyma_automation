"""他サイトとの価格比較"""

import logging

logger = logging.getLogger(__name__)


class PriceComparison:
    """複数ソース間での価格比較を行うクラス"""

    def __init__(self):
        self.sources: list[dict] = []

    def add_source(self, source_name: str, products: list[dict]) -> None:
        """比較対象のソースを追加する"""
        self.sources.append({"name": source_name, "products": products})
        logger.info("Added source: %s (%d products)", source_name, len(products))

    def find_best_price(self, brand: str, product_name: str) -> dict | None:
        """ブランド名と商品名でベストプライスを検索する"""
        best = None
        for source in self.sources:
            for product in source["products"]:
                if (
                    brand.lower() in product.get("brand", "").lower()
                    and product_name.lower() in product.get("name", "").lower()
                ):
                    price = self._parse_price(product.get("sale_price_eur", "0"))
                    if best is None or price < best["price"]:
                        best = {
                            "source": source["name"],
                            "price": price,
                            "product": product,
                        }
        return best

    @staticmethod
    def _parse_price(price_str: str) -> float:
        """価格文字列をfloatに変換する"""
        cleaned = price_str.replace("€", "").replace(",", ".").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

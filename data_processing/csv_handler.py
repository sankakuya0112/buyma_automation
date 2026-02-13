"""CSV入出力処理"""

import logging
from pathlib import Path

import pandas as pd

from config import CSV_OUTPUT_DIR

logger = logging.getLogger(__name__)


class CsvHandler:
    """商品データのCSV入出力を管理するクラス"""

    PRODUCT_COLUMNS = [
        "url",
        "brand",
        "name",
        "original_price_eur",
        "sale_price_eur",
        "description",
        "color",
        "sizes",
        "images",
        "category",
        "name_ja",
        "description_ja",
        "price_jpy",
        "profit_jpy",
        "profit_rate",
    ]

    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or CSV_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_products(self, products: list[dict], filename: str = "products.csv") -> Path:
        """商品データをCSVに保存する"""
        df = pd.DataFrame(products)
        filepath = self.output_dir / filename
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info("Saved %d products to %s", len(products), filepath)
        return filepath

    def load_products(self, filename: str = "products.csv") -> list[dict]:
        """CSVから商品データを読み込む"""
        filepath = self.output_dir / filename
        if not filepath.exists():
            logger.warning("CSV file not found: %s", filepath)
            return []

        df = pd.read_csv(filepath, encoding="utf-8-sig")
        products = df.to_dict(orient="records")
        logger.info("Loaded %d products from %s", len(products), filepath)
        return products

    def merge_products(
        self, existing_file: str, new_products: list[dict], key: str = "url"
    ) -> list[dict]:
        """既存CSVと新規商品データをマージする（重複排除）"""
        existing = self.load_products(existing_file)
        existing_keys = {p.get(key) for p in existing}
        new_items = [p for p in new_products if p.get(key) not in existing_keys]
        merged = existing + new_items
        logger.info(
            "Merged: %d existing + %d new = %d total",
            len(existing),
            len(new_items),
            len(merged),
        )
        return merged

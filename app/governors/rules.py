"""出品可否判定ルール実装"""

import json
import logging
from pathlib import Path
from typing import Tuple

from sqlalchemy.orm import Session

from app.core.models import Listing, RankedProduct, SourceProduct

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _load_json_set(filename: str) -> set[str]:
    """data/ ディレクトリの JSON ファイルからキーセットを読み込む。"""
    path = _DATA_DIR / filename
    if not path.exists():
        logger.warning("Data file not found: %s", path)
        return set()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return {k.lower() for k in data.keys()}
    if isinstance(data, list):
        return {str(v).lower() for v in data}
    return set()


class GovernorRules:
    """
    出品可否判定ルール。
    各チェックメソッドが (True, 理由) を返すと合格。
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self._known_brands: set[str] = _load_json_set("brands.json")
        self._known_categories: set[str] = _load_json_set("categories.json")

    # ------------------------------------------------------------------
    # 個別チェック
    # ------------------------------------------------------------------

    def check_sku(self, product: SourceProduct) -> Tuple[bool, str]:
        """品番が存在するか確認。"""
        if not product.sku or not product.sku.strip():
            return False, "SKU missing"
        return True, "SKU OK"

    def check_price(self, product: SourceProduct) -> Tuple[bool, str]:
        """価格異常チェック（0 以下、または 100,000 超の異常値）。"""
        if product.source_price <= 0 or product.source_price > 100_000:
            return False, f"Abnormal price: {product.source_price}"
        return True, "Price OK"

    def check_category(self, product: SourceProduct) -> Tuple[bool, str]:
        """カテゴリが data/categories.json に存在するか確認。"""
        if not product.category:
            return False, "Category missing"
        if self._known_categories and product.category.lower() not in self._known_categories:
            return False, f"Unknown category: {product.category}"
        return True, "Category OK"

    def check_duplicate(self, product: SourceProduct) -> Tuple[bool, str]:
        """同一 product_url で archived 以外の出品が存在しないか確認。"""
        existing = (
            self.session.query(Listing)
            .join(RankedProduct)
            .join(SourceProduct)
            .filter(
                SourceProduct.product_url == product.product_url,
                Listing.listing_status != "archived",
            )
            .first()
        )
        if existing:
            return False, f"Duplicate listing: {existing.id}"
        return True, "No duplicate"

    def check_brand(self, product: SourceProduct) -> Tuple[bool, str]:
        """ブランドが data/brands.json に登録済みか確認。"""
        if not product.brand:
            return False, "Brand missing"
        if self._known_brands and product.brand.lower() not in self._known_brands:
            return False, f"Unknown brand: {product.brand}"
        return True, "Brand OK"

    def check_images(self, product: SourceProduct) -> Tuple[bool, str]:
        """メイン画像が 1 枚以上存在するか確認。"""
        if not product.image_urls or len(product.image_urls) == 0:
            return False, "No images"
        return True, f"Images OK ({len(product.image_urls)} found)"

    def check_profit_margin(self, ranked: RankedProduct) -> Tuple[bool, str]:
        """利益率が 80% 以上の場合は疑わしいとして reject。"""
        if ranked.est_margin_pct >= 80:
            return False, f"Suspiciously high margin: {ranked.est_margin_pct}%"
        return True, "Margin OK"

    # ------------------------------------------------------------------
    # 複合判定
    # ------------------------------------------------------------------

    def evaluate(
        self,
        product: SourceProduct,
        ranked: RankedProduct,
    ) -> Tuple[str, str]:
        """
        全チェックを実行して総合判定を返す。

        Returns:
            (decision, reason)
            decision: "approved" | "hold" | "reject"
        """
        checks = [
            self.check_sku(product),
            self.check_price(product),
            self.check_category(product),
            self.check_duplicate(product),
            self.check_brand(product),
            self.check_images(product),
            self.check_profit_margin(ranked),
        ]

        failures = [reason for passed, reason in checks if not passed]

        if not failures:
            return "approved", "All checks passed"
        return "reject", "; ".join(failures)


def run_governor(session: Session, ranked_product_id: int) -> None:
    """
    1 件の RankedProduct に対して Governor 判定を実行し DB に保存する。

    Args:
        session: SQLAlchemy セッション
        ranked_product_id: 判定対象の RankedProduct.id
    """
    ranked = session.get(RankedProduct, ranked_product_id)
    if ranked is None:
        logger.error("RankedProduct not found: %d", ranked_product_id)
        return

    product = ranked.source_product
    governor = GovernorRules(session)
    decision, reason = governor.evaluate(product, ranked)

    ranked.governor_decision = decision
    ranked.governor_notes = reason
    session.commit()

    logger.info("Product %d: %s - %s", product.id, decision, reason)

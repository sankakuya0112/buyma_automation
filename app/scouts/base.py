"""共通スクレイパー抽象基底クラス"""

import logging
from abc import ABC, abstractmethod
from typing import List

from sqlalchemy.orm import Session

from app.core.models import SourceProduct

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    すべてのスクレイパーが継承する抽象基底クラス。

    サブクラスの責務:
    - scrape() を実装（サイト固有のスクレイピングロジック）
    - 必要に応じて normalize() をオーバーライド
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.source_name: str = ""  # サブクラスで設定: "baseblu", "yoox" etc.

    @abstractmethod
    def scrape(self) -> List[dict]:
        """
        サイト固有のスクレイピングを実装する。

        Returns:
            商品情報 dict のリスト。各 dict は以下のキーを持つ:
                product_url (str)
                brand (str)
                title (str)
                sku (str | None)
                color (str | None)
                category (str | None)
                source_price (float)
                currency (str)          例: "EUR"
                shipping_cost (float)
                image_urls (list[str])
                sub_images (list[dict]) 例: [{"url": ..., "alt_text": ...}]
                description_en (str | None)
                stock_status (str)      例: "in_stock"
        """

    def normalize(self, raw_products: List[dict]) -> List[dict]:
        """
        取得データを正規化する。
        デフォルト実装はそのまま返す。サブクラスで必要に応じてオーバーライド。
        """
        return raw_products

    def save_to_db(self, products: List[dict]) -> List[SourceProduct]:
        """
        商品データを source_products テーブルに保存する。
        product_url で一意性を確保し、既存レコードは更新、新規は挿入する。

        Args:
            products: normalize() 済みの商品 dict リスト

        Returns:
            保存した SourceProduct インスタンスのリスト
        """
        saved: List[SourceProduct] = []

        for data in products:
            url = data.get("product_url", "")
            existing = (
                self.session.query(SourceProduct)
                .filter(SourceProduct.product_url == url)
                .first()
            )

            if existing:
                # 既存レコードを更新
                for key, value in data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                saved.append(existing)
            else:
                # 新規挿入
                source_product = SourceProduct(
                    source_name=self.source_name,
                    **data,
                )
                self.session.add(source_product)
                saved.append(source_product)

        self.session.commit()
        logger.info("Saved %d products from %s", len(saved), self.source_name)
        return saved

    def run(self) -> List[SourceProduct]:
        """
        スクレイピング → 正規化 → DB 保存を一括実行する。

        Returns:
            保存した SourceProduct インスタンスのリスト
        """
        logger.info("Starting scrape: %s", self.source_name)
        raw = self.scrape()
        normalized = self.normalize(raw)
        saved = self.save_to_db(normalized)
        logger.info("Completed: %d products saved from %s", len(saved), self.source_name)
        return saved

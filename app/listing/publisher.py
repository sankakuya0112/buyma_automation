"""BUYMA 出品実行（Playwright 自動化）"""

import logging
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.models import Listing, RankedProduct
from app.listing.buyma_client import BUYMAClient
from app.listing.draft_builder import build_draft

logger = logging.getLogger(__name__)

# 出品間隔（秒）: BOT 検出回避のため次の出品まで待機
_LISTING_INTERVAL_SECONDS = 10


class ListingPublisher:
    """
    BUYMA に出品を公開するクラス。
    Playwright の Page オブジェクトを受け取り、1 件ずつ出品処理を実行する。
    """

    def __init__(self, page) -> None:
        self.page = page
        self.client = BUYMAClient(page)

    def publish(
        self,
        session: Session,
        ranked_product_id: int,
        draft_only: bool = False,
    ) -> Optional[str]:
        """
        1 件の出品を実行する。

        処理フロー:
            1. ListingDraft 生成
            2. BUYMA 出品フォームへ移動
            3. 基本情報・説明文・価格を入力
            4. 画像アップロード（ページ遷移直後に実行）
            5. 出品オプション設定
            6. 公開 or 下書き保存
            7. listings テーブルに記録
            8. 次の出品まで待機

        Args:
            session: SQLAlchemy セッション
            ranked_product_id: 出品対象の RankedProduct.id
            draft_only: True の場合、下書きのみ（BUYMA に公開しない）

        Returns:
            BUYMA item_id（成功時）/ None（draft_only 時）

        Raises:
            Exception: 出品処理中の予期しないエラー
        """
        ranked = session.get(RankedProduct, ranked_product_id)
        if ranked is None:
            raise ValueError(f"RankedProduct {ranked_product_id} not found")

        product = ranked.source_product

        try:
            # Step 1: 出品データ生成
            draft = build_draft(session, ranked_product_id)
            logger.info("Built draft for product %d", product.id)

            # Step 2: 出品フォームへ移動
            self.client.navigate_to_listing_form()
            self.page.wait_for_load_state("networkidle")

            # Step 3: 基本情報入力
            if draft.brand:
                self.client.set_field("brand", draft.brand)
            self.client.set_field("title", draft.title)
            if draft.category:
                self.client.set_field("category", draft.category)
            if draft.sku:
                self.client.set_field("sku", draft.sku)

            # Step 4: 説明文入力
            self.client.set_field("description", draft.description)

            # Step 5: 価格入力
            self.client.set_field("price", str(int(draft.price_jpy)))

            # Step 6: 画像アップロード（ページ遷移直後に実行）
            if draft.image_urls:
                self.client.upload_images(draft.image_urls)

            # Step 7: 出品オプション設定
            self.client.set_listing_options(
                buyable=True,
                purchase_limit_days=90,
                tax_included=True,
                buy_location="Italy",
                ship_from="Japan",
            )

            # Step 8: 公開 or 下書き保存
            item_id: Optional[str]
            if draft_only:
                self.client.save_as_draft()
                logger.info("Saved as draft: product %d", product.id)
                item_id = None
            else:
                item_id = self.client.publish()
                logger.info("Published: product %d → item_id %s", product.id, item_id)

            # Step 9: DB に記録
            listing = Listing(
                ranked_product_id=ranked_product_id,
                buyma_item_id=item_id,
                listing_status="draft" if draft_only else "published",
                listing_price_jpy=draft.price_jpy,
                title=draft.title,
                description=draft.description,
                listed_at=None if draft_only else datetime.utcnow(),
            )
            session.add(listing)
            session.commit()

            return item_id

        except Exception as exc:
            logger.error("Failed to publish product %d: %s", product.id, exc)
            raise

        finally:
            # BOT 検出回避: 次の出品まで待機
            time.sleep(_LISTING_INTERVAL_SECONDS)

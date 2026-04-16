"""
在庫監視モジュール（Guard）。

PROFIT_FIRST タスク 2-2 / PHASE2_GUARD.md の最小実装。
公開出品中の商品について仕入れ先の在庫状況を確認し、
売り切れた商品を BUYMA 側で自動停止する。

BaseBlu は Shopify ベースのため、product.json エンドポイントで
variants[*].available を確認する（Playwright 不要、高速）。

他の仕入れ先を追加する場合は _check_availability() をオーバーライド
するサブクラスを作成すること。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import requests

from app.core.models import (
    InventoryCheck,
    Listing,
    ListingEvent,
    RankedProduct,
    SourceProduct,
)

logger = logging.getLogger(__name__)

SHOPIFY_PRODUCT_JSON_TIMEOUT = 15


class StockCheckResult:
    """1 件の在庫チェック結果。"""

    __slots__ = ("listing_id", "available", "current_price", "error")

    def __init__(
        self,
        listing_id: int,
        available: bool,
        current_price: Optional[float] = None,
        error: Optional[str] = None,
    ):
        self.listing_id = listing_id
        self.available = available
        self.current_price = current_price
        self.error = error


class StockMonitor:
    """
    仕入れ先サイトの在庫を JSON API で監視する。

    使い方:
        from app.guard.stock_monitor import StockMonitor
        monitor = StockMonitor()
        summary = monitor.run_all(session)
        print(summary)
    """

    def __init__(self, session_headers: Optional[dict] = None):
        self._headers = session_headers or {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # 1 件チェック
    # ------------------------------------------------------------------

    def check_stock(self, session, listing_id: int) -> StockCheckResult:
        """
        1 件の出品について仕入れ先の在庫を確認する。

        Returns:
            StockCheckResult（available / current_price / error）
        """
        listing = session.get(Listing, listing_id)
        if listing is None:
            return StockCheckResult(listing_id, False, error="Listing not found")

        ranked: RankedProduct = listing.ranked_product
        product: SourceProduct = ranked.source_product
        url = product.product_url

        try:
            available, current_price = self._check_availability(url, product.source_name)
        except Exception as exc:
            logger.error("Stock check failed for listing %d: %s", listing_id, exc)
            self._record_check(session, product.id, False, None, str(exc))
            return StockCheckResult(listing_id, False, error=str(exc))

        self._record_check(session, product.id, available, current_price)
        return StockCheckResult(listing_id, available, current_price)

    # ------------------------------------------------------------------
    # 全件チェック + 自動停止 / 再出品
    # ------------------------------------------------------------------

    def run_all(self, session) -> dict:
        """
        全アクティブ出品の在庫チェックを実行し、
        売り切れ商品は自動停止、復帰した商品は再出品する。

        Returns:
            {total, available, stopped, relisted, failed}
        """
        active_listings = (
            session.query(Listing)
            .filter(Listing.listing_status.in_(["published", "stopped"]))
            .all()
        )

        summary = {
            "total": len(active_listings),
            "available": 0,
            "stopped": 0,
            "relisted": 0,
            "failed": 0,
        }

        for listing in active_listings:
            result = self.check_stock(session, listing.id)

            if result.error:
                summary["failed"] += 1
                continue

            if result.available:
                summary["available"] += 1
                if listing.listing_status == "stopped":
                    self._relist(session, listing, result.current_price)
                    summary["relisted"] += 1
            else:
                if listing.listing_status == "published":
                    self._stop(session, listing)
                    summary["stopped"] += 1

        session.commit()
        logger.info("Guard run_all completed: %s", summary)
        return summary

    # ------------------------------------------------------------------
    # 在庫確認ロジック（サイト別）
    # ------------------------------------------------------------------

    def _check_availability(
        self, product_url: str, source_name: str
    ) -> tuple[bool, Optional[float]]:
        """
        仕入れ先の在庫と現在価格を取得する。

        BaseBlu（Shopify）の場合は product.json エンドポイントを使用。
        他のサイトを追加する場合はここに分岐を追加する。
        """
        if source_name == "baseblu" or "baseblu.com" in product_url:
            return self._check_baseblu(product_url)
        # 将来の拡張ポイント
        # if source_name == "yoox":
        #     return self._check_yoox(product_url)
        return self._check_baseblu(product_url)

    def _check_baseblu(self, product_url: str) -> tuple[bool, Optional[float]]:
        """
        BaseBlu の product.json エンドポイントで在庫を確認する。

        Shopify の product.json は variants 配列を持ち、各 variant に
        available (bool) と price (str) がある。1 つでも available な
        variant があれば「在庫あり」と判定。
        """
        json_url = product_url.rstrip("/") + ".json"
        resp = requests.get(
            json_url,
            headers=self._headers,
            timeout=SHOPIFY_PRODUCT_JSON_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        product_data = data.get("product", {})
        variants = product_data.get("variants", [])

        if not variants:
            return False, None

        any_available = any(v.get("available", False) for v in variants)

        # 最安の available variant の価格を取得
        current_price = None
        for v in variants:
            if v.get("available", False):
                try:
                    price = float(v.get("price", 0))
                    if current_price is None or price < current_price:
                        current_price = price
                except (ValueError, TypeError):
                    continue

        return any_available, current_price

    # ------------------------------------------------------------------
    # DB 操作
    # ------------------------------------------------------------------

    def _record_check(
        self,
        session,
        source_product_id: int,
        stock_available: bool,
        price_at_check: Optional[float],
        notes: Optional[str] = None,
    ) -> None:
        """InventoryCheck レコードを作成する。"""
        check = InventoryCheck(
            source_product_id=source_product_id,
            stock_available=stock_available,
            price_at_check=price_at_check,
            notes=notes or f"Guard check at {datetime.utcnow().isoformat()}",
        )
        session.add(check)

    def _stop(self, session, listing: Listing) -> None:
        """出品を停止状態にする。"""
        listing.listing_status = "stopped"
        listing.stopped_at = datetime.utcnow()

        event = ListingEvent(
            listing_id=listing.id,
            event_type="stopped",
            detail={"reason": "guard_stock_unavailable"},
        )
        session.add(event)
        logger.warning(
            "STOPPED listing %d (%s) — stock unavailable",
            listing.id,
            listing.title[:50],
        )

    def _relist(
        self, session, listing: Listing, current_price: Optional[float]
    ) -> None:
        """停止中の出品を再出品状態にする。"""
        listing.listing_status = "published"
        listing.relisted_at = datetime.utcnow()

        event = ListingEvent(
            listing_id=listing.id,
            event_type="relisted",
            detail={
                "reason": "guard_stock_restored",
                "price_at_relist": current_price,
            },
        )
        session.add(event)
        logger.info(
            "RELISTED listing %d (%s) — stock restored",
            listing.id,
            listing.title[:50],
        )

#!/usr/bin/env python3
"""
BUYMA 自動出品パイプライン。

Usage:
    python3 scripts/run_pipeline.py [OPTIONS]

Options:
    --test              1 件テスト実行
    --draft             下書きのみ（BUYMA に公開しない）
    --skip-scrape       スクレイピングをスキップ（既存 DB データを使用）
    --from N            N 件目から再開
    --resume            前回中断した位置から再開（未出品の approved 商品を処理）
    --log-level LEVEL   ログレベル（DEBUG / INFO / WARNING / ERROR、デフォルト: INFO）
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_config
from app.core.db import init_db
from app.core.logger import setup_logger
from app.core.models import Base, Listing, RankedProduct, SourceProduct
from app.governors.rules import GovernorRules

logger = setup_logger("run_pipeline")

# BUYMA 手数料率
_BUYMA_COMMISSION_RATE = 0.058


class Pipeline:
    """パイプライン実行エンジン。"""

    def __init__(self, config, session_factory) -> None:
        self.config = config
        self.session_factory = session_factory

    # ------------------------------------------------------------------
    # Step 1: スクレイピング
    # ------------------------------------------------------------------

    def step_scrape(self) -> int:
        """
        BaseBlu からセール商品をスクレイピングして source_products に保存する。

        Returns:
            スクレイプされた商品数
        """
        logger.info("=== STEP 1: Scraping ===")

        from app.scouts.baseblu import BaseBluScraper

        session = self.session_factory()
        try:
            scraper = BaseBluScraper(session)
            products = scraper.run()
            logger.info("Scraped %d products", len(products))
            return len(products)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Step 2: 利益計算
    # ------------------------------------------------------------------

    def step_profit_calc(self) -> int:
        """
        source_products の全件に対して利益計算を実施し、ranked_products に保存する。
        既に ranked_products レコードが存在する商品はスキップする。

        Returns:
            ランク付けされた商品数
        """
        logger.info("=== STEP 2: Profit Calculation ===")

        session = self.session_factory()
        try:
            source_products = session.query(SourceProduct).all()
            added = 0

            for product in source_products:
                existing_rank = (
                    session.query(RankedProduct)
                    .filter(RankedProduct.source_product_id == product.id)
                    .first()
                )
                if existing_rank:
                    continue

                est_profit, est_margin = self._calculate_profit(product)

                if (
                    est_profit >= self.config.min_profit_jpy
                    and est_margin >= self.config.target_margin_pct
                ):
                    lane = "core"
                    rank_score = 80.0
                    decision_reason = f"Profit: ¥{est_profit:.0f}, Margin: {est_margin:.1f}%"
                else:
                    lane = "long_tail"
                    rank_score = 50.0
                    decision_reason = (
                        f"Below target (profit=¥{est_profit:.0f}, margin={est_margin:.1f}%)"
                    )

                ranked = RankedProduct(
                    source_product_id=product.id,
                    est_profit_jpy=est_profit,
                    est_margin_pct=est_margin,
                    lane=lane,
                    rank_score=rank_score,
                    decision_reason=decision_reason,
                )
                session.add(ranked)
                added += 1

            session.commit()
            total = session.query(RankedProduct).count()
            logger.info("Ranked %d products (added %d new)", total, added)
            return total
        finally:
            session.close()

    def _calculate_profit(self, product: SourceProduct) -> tuple[float, float]:
        """
        商品の推定利益（円）と利益率（%）を計算する。

        計算式:
            cost_jpy  = (source_price + shipping_cost) * exchange_rate
            list_price = cost_jpy * (1 + target_margin) / (1 - commission_rate)
            profit_jpy = list_price * (1 - commission_rate) - cost_jpy
            margin_pct = (profit_jpy / cost_jpy) * 100

        Returns:
            (est_profit_jpy, est_margin_pct)
        """
        import math

        from app.utils.currency import currency as fx

        exchange_rate = fx.get_rate(product.currency, "JPY")
        cost_jpy = (product.source_price + product.shipping_cost) * exchange_rate
        target_margin = self.config.target_margin_pct / 100

        list_price = math.ceil(
            cost_jpy * (1 + target_margin) / (1 - _BUYMA_COMMISSION_RATE) / 100
        ) * 100

        profit_jpy = list_price * (1 - _BUYMA_COMMISSION_RATE) - cost_jpy
        margin_pct = (profit_jpy / cost_jpy * 100) if cost_jpy > 0 else 0.0

        return round(profit_jpy, 2), round(margin_pct, 2)

    # ------------------------------------------------------------------
    # Step 3: Governor（出品可否判定）
    # ------------------------------------------------------------------

    def step_governor(self) -> int:
        """
        未判定の ranked_products に対して Governor 判定を実施する。

        Returns:
            "approved" になった件数
        """
        logger.info("=== STEP 3: Governor ===")

        session = self.session_factory()
        try:
            pending = (
                session.query(RankedProduct)
                .filter(RankedProduct.governor_decision == "pending")
                .all()
            )

            approved_count = 0
            for ranked in pending:
                product = ranked.source_product
                governor = GovernorRules(session)
                decision, reason = governor.evaluate(product, ranked)

                ranked.governor_decision = decision
                ranked.governor_notes = reason
                session.commit()

                if decision == "approved":
                    approved_count += 1
                    logger.info("[APPROVED] %s %s", product.brand, product.title)
                else:
                    logger.info("[%s] product %d: %s", decision.upper(), product.id, reason)

            logger.info("Governor result: %d approved (of %d evaluated)", approved_count, len(pending))
            return approved_count
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Step 4: Listing（BUYMA 出品）
    # ------------------------------------------------------------------

    def step_listing(
        self,
        draft_only: bool = False,
        test_count: Optional[int] = None,
        from_idx: int = 0,
    ) -> int:
        """
        approved 商品を BUYMA に出品する。

        Args:
            draft_only: True の場合、下書きのみ（BUYMA に公開しない）
            test_count: テスト件数（指定した件数だけ処理）
            from_idx: 開始インデックス（再開用）

        Returns:
            出品した件数
        """
        logger.info("=== STEP 4: Listing ===")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("playwright not installed. Run: pip install playwright && playwright install")
            return 0

        from app.listing.publisher import ListingPublisher

        session = self.session_factory()
        try:
            # approved かつ未出品の商品を取得
            approved = (
                session.query(RankedProduct)
                .filter(RankedProduct.governor_decision == "approved")
                .all()
            )

            to_list = [
                ranked for ranked in approved
                if not session.query(Listing)
                .filter(Listing.ranked_product_id == ranked.id)
                .first()
            ]

            # 再開・テスト対応
            if from_idx > 0:
                to_list = to_list[from_idx:]
            if test_count:
                to_list = to_list[:test_count]

            logger.info("Publishing %d products (draft_only=%s)", len(to_list), draft_only)

            published_count = 0
            with sync_playwright() as p:
                launch_kwargs = {"headless": self.config.headless}
                if self.config.chromium_executable_path:
                    launch_kwargs["executable_path"] = self.config.chromium_executable_path
                browser = p.chromium.launch(**launch_kwargs)
                page = browser.new_page()

                try:
                    publisher = ListingPublisher(page)
                    if not publisher.client.login():
                        logger.error("BUYMA login failed. Aborting listing step.")
                        return 0

                    for idx, ranked in enumerate(to_list):
                        try:
                            item_id = publisher.publish(
                                session,
                                ranked.id,
                                draft_only=draft_only,
                            )
                            published_count += 1
                            logger.info(
                                "[%d/%d] Published: item_id=%s",
                                idx + 1,
                                len(to_list),
                                item_id,
                            )
                        except Exception as exc:
                            logger.error("Failed to publish ranked %d: %s", ranked.id, exc)
                finally:
                    browser.close()

            logger.info("Published %d products", published_count)
            return published_count
        finally:
            session.close()

    # ------------------------------------------------------------------
    # フルパイプライン
    # ------------------------------------------------------------------

    def run_all(
        self,
        skip_scrape: bool = False,
        draft_only: bool = False,
        test: bool = False,
        from_idx: int = 0,
        resume: bool = False,
    ) -> None:
        """
        フルパイプラインを実行する（スクレイピング → 利益計算 → Governor → 出品）。

        Args:
            skip_scrape: True でスクレイピングをスキップ
            draft_only: True で下書きのみ
            test: True で 1 件のみテスト実行
            from_idx: 出品開始インデックス
            resume: True で前回中断位置から再開（from_idx と組み合わせ可）
        """
        logger.info("Pipeline starting...")

        if not skip_scrape:
            self.step_scrape()

        self.step_profit_calc()
        self.step_governor()

        test_count = 1 if test else None
        self.step_listing(
            draft_only=draft_only,
            test_count=test_count,
            from_idx=from_idx,
        )

        logger.info("Pipeline completed.")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="BUYMA 自動出品パイプライン",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--test", action="store_true", help="1 件テスト実行")
    parser.add_argument("--draft", action="store_true", help="下書きのみ（BUYMA に公開しない）")
    parser.add_argument("--skip-scrape", action="store_true", help="スクレイピングをスキップ")
    parser.add_argument(
        "--from",
        type=int,
        dest="from_idx",
        default=0,
        metavar="N",
        help="N 件目から再開",
    )
    parser.add_argument("--resume", action="store_true", help="前回中断した位置から再開")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル（デフォルト: INFO）",
    )

    args = parser.parse_args()

    # 設定読み込み・DB 初期化
    config = get_config()
    init_db(config.db_path)

    engine = create_engine(f"sqlite:///{config.db_path}", echo=False)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)

    # パイプライン実行
    pipeline = Pipeline(config, SessionFactory)
    pipeline.run_all(
        skip_scrape=args.skip_scrape,
        draft_only=args.draft,
        test=args.test,
        from_idx=args.from_idx,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()

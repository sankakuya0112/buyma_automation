"""全パイプライン実行スクリプト

使い方:
  python3 scripts/run_all.py               # 通常実行（baseblu.comからスクレイピング）
  python3 scripts/run_all.py --test        # テストモード（モックデータで動作確認）
  python3 scripts/run_all.py --pages 2     # ページ数を指定
  python3 scripts/run_all.py --auto-list   # BUYMA出品まで自動実行
"""

import argparse
import logging
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import LOG_DIR


# テストモード用モック商品データ
MOCK_PRODUCTS = [
    {
        "handle": "test-dress-001",
        "url": "https://www.baseblu.com/en-us/products/test-dress-001",
        "brand": "TestBrand",
        "name": "Silk Midi Dress",
        "original_price_eur": "450.00",
        "sale_price_eur": "225.00",
        "discount_rate": "50%",
        "description": "Elegant silk midi dress with floral print.",
        "color": "blue",
        "sizes": "XS, S, M, L",
        "available_sizes": "S, M",
        "images": "https://cdn.shopify.com/test/dress.jpg",
        "category": "dress",
        "tags": "silk, midi, floral",
        "collection": "sale-woman",
    },
    {
        "handle": "test-jacket-002",
        "url": "https://www.baseblu.com/en-us/products/test-jacket-002",
        "brand": "TestBrand",
        "name": "Leather Biker Jacket",
        "original_price_eur": "890.00",
        "sale_price_eur": "445.00",
        "discount_rate": "50%",
        "description": "Classic leather biker jacket with silver hardware.",
        "color": "black",
        "sizes": "S, M, L, XL",
        "available_sizes": "M, L, XL",
        "images": "https://cdn.shopify.com/test/jacket.jpg",
        "category": "jacket",
        "tags": "leather, biker",
        "collection": "sale-woman",
    },
    {
        "handle": "test-sneakers-003",
        "url": "https://www.baseblu.com/en-us/products/test-sneakers-003",
        "brand": "AnotherBrand",
        "name": "Canvas Low Sneakers",
        "original_price_eur": "180.00",
        "sale_price_eur": "90.00",
        "discount_rate": "50%",
        "description": "Lightweight canvas sneakers for everyday wear.",
        "color": "white",
        "sizes": "38, 39, 40, 41, 42",
        "available_sizes": "39, 40, 41",
        "images": "https://cdn.shopify.com/test/sneakers.jpg",
        "category": "sneakers",
        "tags": "canvas, casual",
        "collection": "sale-man",
    },
]


def setup_logging(log_level: str = "INFO") -> None:
    """ロギングを設定する"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "run_all.log"

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_pipeline(
    pages: int = 5,
    auto_list: bool = False,
    test_mode: bool = False,
    output_filename: str = "run_all_output.csv",
) -> int:
    """スクレイピング→価格計算→翻訳の全パイプラインを実行する

    Args:
        pages: コレクションごとの最大取得ページ数（テストモード時は無視）
        auto_list: Trueの場合、BUYMA出品まで自動実行
        test_mode: Trueの場合、モックデータを使用してネットワークアクセスをスキップ
        output_filename: 出力CSVファイル名

    Returns:
        処理した商品数（エラー時は -1）
    """
    from data_processing.csv_handler import CsvHandler
    from data_processing.price_calculator import PriceCalculator
    from data_processing.text_translator import TextTranslator

    logger = logging.getLogger(__name__)

    # ---- Step 1: データ取得 ----
    if test_mode:
        logger.info("[TEST MODE] Using mock product data (%d items)", len(MOCK_PRODUCTS))
        products = list(MOCK_PRODUCTS)  # コピーして使用
    else:
        from scrapers.baseblu_scraper import BasebluScraper

        logger.info("Step 1: Scraping baseblu.com (max_pages=%d per collection)", pages)
        scraper = BasebluScraper()
        products = scraper.scrape_sale_products(max_pages=pages)

    if not products:
        logger.warning("No products found. Aborting pipeline.")
        return 0

    logger.info("Products fetched: %d", len(products))

    # ---- Step 2: 価格計算 ----
    logger.info("Step 2: Calculating JPY prices")
    calculator = PriceCalculator()
    products = [calculator.enrich_product_with_price(p) for p in products]

    # ---- Step 3: 翻訳 ----
    logger.info("Step 3: Generating Japanese text")
    translator = TextTranslator()
    products = [translator.enrich_product_with_translations(p) for p in products]

    # ---- Step 4: CSV保存 ----
    csv_handler = CsvHandler()
    filepath = csv_handler.save_products(products, filename=output_filename)
    logger.info("Output saved: %s", filepath)

    # ---- Step 5: BUYMA出品（オプション） ----
    if auto_list:
        if test_mode:
            logger.info("[TEST MODE] Skipping BUYMA listing")
        else:
            from buyma.buyma_automation import BuymaAutomation

            logger.info("Step 4: Listing products on BUYMA")
            automation = BuymaAutomation()
            try:
                if automation.start():
                    results = automation.list_products(products)
                    success_count = sum(1 for r in results if r["success"])
                    logger.info(
                        "Listing complete: %d/%d successful", success_count, len(results)
                    )
                else:
                    logger.error("Failed to start BUYMA automation")
            finally:
                automation.close()

    return len(products)


def print_summary(products_count: int, test_mode: bool, elapsed: float) -> None:
    """実行結果のサマリを表示する"""
    mode_label = "[TEST MODE] " if test_mode else ""
    print()
    print("=" * 50)
    print(f"  {mode_label}Pipeline complete")
    print(f"  Products processed : {products_count}")
    print(f"  Elapsed            : {elapsed:.1f}s")
    print("=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BUYMA自動出品 全パイプライン実行スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="テストモード: モックデータを使用し、外部ネットワークアクセスをスキップする",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="コレクションごとの最大取得ページ数（デフォルト: 5、テストモード時は無視）",
    )
    parser.add_argument(
        "--auto-list",
        action="store_true",
        help="処理後にBUYMAへの自動出品まで実行する（テストモード時はスキップ）",
    )
    parser.add_argument(
        "--output",
        default="run_all_output.csv",
        help="出力CSVファイル名（デフォルト: run_all_output.csv）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル（デフォルト: INFO）",
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    import time

    start = time.monotonic()

    try:
        count = run_pipeline(
            pages=args.pages,
            auto_list=args.auto_list,
            test_mode=args.test,
            output_filename=args.output,
        )
    except Exception:
        logging.getLogger(__name__).exception("Pipeline failed with an unexpected error")
        sys.exit(1)

    elapsed = time.monotonic() - start
    print_summary(count, args.test, elapsed)


if __name__ == "__main__":
    main()

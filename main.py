"""BUYMA自動出品ツール - エントリーポイント"""

import argparse
import logging
import sys
from pathlib import Path

from config import LOG_DIR


def setup_logging(log_level: str = "INFO") -> None:
    """ロギングを設定する"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "automation.log"

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def cmd_scrape(args: argparse.Namespace) -> None:
    """スクレイピング実行"""
    from data_processing.csv_handler import CsvHandler
    from scrapers.baseblu_scraper import BasebluScraper

    logger = logging.getLogger(__name__)

    collections = args.collections if args.collections else None
    logger.info(
        "Starting baseblu scraping (max_pages=%d, collections=%s)",
        args.pages,
        collections or "all",
    )

    scraper = BasebluScraper()
    products = scraper.scrape_sale_products(
        max_pages=args.pages,
        collections=collections,
    )

    if products:
        csv_handler = CsvHandler()

        # --mergeオプション: 既存CSVとマージ
        if args.merge:
            products = csv_handler.merge_products(
                args.output, products, key="handle"
            )

        filepath = csv_handler.save_products(products, filename=args.output)
        logger.info("Saved %d products to %s", len(products), filepath)
    else:
        logger.warning("No products found")


def cmd_calculate(args: argparse.Namespace) -> None:
    """価格計算実行"""
    from data_processing.csv_handler import CsvHandler
    from data_processing.price_calculator import PriceCalculator

    logger = logging.getLogger(__name__)
    logger.info("Calculating prices for %s", args.input)

    csv_handler = CsvHandler()
    products = csv_handler.load_products(args.input)

    if not products:
        logger.warning("No products to process")
        return

    calculator = PriceCalculator()
    enriched = [calculator.enrich_product_with_price(p) for p in products]

    output_file = args.output or f"priced_{args.input}"
    csv_handler.save_products(enriched, filename=output_file)
    logger.info("Price calculation complete: %d products", len(enriched))


def cmd_translate(args: argparse.Namespace) -> None:
    """翻訳実行"""
    from data_processing.csv_handler import CsvHandler
    from data_processing.text_translator import TextTranslator

    logger = logging.getLogger(__name__)
    logger.info("Translating products from %s", args.input)

    csv_handler = CsvHandler()
    products = csv_handler.load_products(args.input)

    if not products:
        logger.warning("No products to process")
        return

    translator = TextTranslator()
    translated = [translator.enrich_product_with_translations(p) for p in products]

    output_file = args.output or f"translated_{args.input}"
    csv_handler.save_products(translated, filename=output_file)
    logger.info("Translation complete: %d products", len(translated))


def cmd_list(args: argparse.Namespace) -> None:
    """BUYMA出品実行"""
    from buyma.buyma_automation import BuymaAutomation
    from data_processing.csv_handler import CsvHandler

    logger = logging.getLogger(__name__)
    logger.info("Starting BUYMA listing from %s", args.input)

    csv_handler = CsvHandler()
    products = csv_handler.load_products(args.input)

    if not products:
        logger.warning("No products to list")
        return

    automation = BuymaAutomation()
    try:
        if not automation.start():
            logger.error("Failed to start BUYMA automation")
            return

        results = automation.list_products(products)
        success_count = sum(1 for r in results if r["success"])
        logger.info("Listing complete: %d/%d successful", success_count, len(results))

    finally:
        automation.close()


def cmd_pipeline(args: argparse.Namespace) -> None:
    """全工程を一括実行する"""
    from data_processing.csv_handler import CsvHandler
    from data_processing.price_calculator import PriceCalculator
    from data_processing.text_translator import TextTranslator
    from scrapers.baseblu_scraper import BasebluScraper

    logger = logging.getLogger(__name__)
    logger.info("Starting full pipeline")

    # 1. スクレイピング
    logger.info("Step 1: Scraping baseblu.com")
    scraper = BasebluScraper()
    products = scraper.scrape_sale_products(max_pages=args.pages)
    if not products:
        logger.warning("No products found, aborting pipeline")
        return

    # 2. 価格計算
    logger.info("Step 2: Calculating prices")
    calculator = PriceCalculator()
    products = [calculator.enrich_product_with_price(p) for p in products]

    # 3. 翻訳
    logger.info("Step 3: Translating to Japanese")
    translator = TextTranslator()
    products = [translator.enrich_product_with_translations(p) for p in products]

    # 4. CSV保存
    csv_handler = CsvHandler()
    csv_handler.save_products(products, filename="pipeline_output.csv")
    logger.info("Pipeline complete: %d products processed", len(products))

    # 5. BUYMA出品（--listオプション指定時のみ）
    if args.auto_list:
        from buyma.buyma_automation import BuymaAutomation

        logger.info("Step 4: Listing on BUYMA")
        automation = BuymaAutomation()
        try:
            if automation.start():
                results = automation.list_products(products)
                success_count = sum(1 for r in results if r["success"])
                logger.info("Listing complete: %d/%d successful", success_count, len(results))
            else:
                logger.error("Failed to start BUYMA automation")
        finally:
            automation.close()


def main() -> None:
    """メインエントリーポイント"""
    parser = argparse.ArgumentParser(description="BUYMA自動出品ツール")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル（デフォルト: INFO）",
    )
    subparsers = parser.add_subparsers(dest="command", help="実行コマンド")

    # scrape コマンド
    scrape_parser = subparsers.add_parser("scrape", help="baseblu.comからスクレイピング")
    scrape_parser.add_argument("--pages", type=int, default=5, help="コレクションごとの取得ページ数")
    scrape_parser.add_argument("--output", default="products.csv", help="出力ファイル名")
    scrape_parser.add_argument(
        "--collections",
        nargs="+",
        default=None,
        help="対象コレクション名（例: sale-woman sale-man）省略時は全セール",
    )
    scrape_parser.add_argument(
        "--merge",
        action="store_true",
        help="既存CSVとマージ（重複排除）",
    )

    # calculate コマンド
    calc_parser = subparsers.add_parser("calculate", help="価格計算")
    calc_parser.add_argument("--input", default="products.csv", help="入力ファイル名")
    calc_parser.add_argument("--output", default=None, help="出力ファイル名")

    # translate コマンド
    translate_parser = subparsers.add_parser("translate", help="テキスト翻訳")
    translate_parser.add_argument("--input", default="products.csv", help="入力ファイル名")
    translate_parser.add_argument("--output", default=None, help="出力ファイル名")

    # list コマンド
    list_parser = subparsers.add_parser("list", help="BUYMA出品")
    list_parser.add_argument("--input", default="products.csv", help="入力ファイル名")

    # pipeline コマンド
    pipeline_parser = subparsers.add_parser("pipeline", help="全工程一括実行")
    pipeline_parser.add_argument("--pages", type=int, default=5, help="取得ページ数")
    pipeline_parser.add_argument("--auto-list", action="store_true", help="出品まで自動実行")

    args = parser.parse_args()
    setup_logging(args.log_level)

    commands = {
        "scrape": cmd_scrape,
        "calculate": cmd_calculate,
        "translate": cmd_translate,
        "list": cmd_list,
        "pipeline": cmd_pipeline,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

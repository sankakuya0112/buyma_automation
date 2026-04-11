#!/usr/bin/env python3
"""BUYMA 全商品一括出品スクリプト

使い方:
  python3 scripts/buyma_auto_listing.py          # 全商品を一括出品
  python3 scripts/buyma_auto_listing.py --test   # まず1件だけ試す
  python3 scripts/buyma_auto_listing.py --resume # 途中から再開
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# プロジェクトルートをパスに追加（scriptsサブディレクトリから実行可能にする）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import CSV_OUTPUT_DIR, LOG_DIR  # noqa: E402
from buyma.buyma_automation import BuymaAutomation  # noqa: E402
from data_processing.csv_handler import CsvHandler  # noqa: E402
from data_processing.price_calculator import PriceCalculator  # noqa: E402
from data_processing.text_translator import TextTranslator  # noqa: E402
from scrapers.baseblu_scraper import BasebluScraper  # noqa: E402

# 出力ファイル名（pipeline実行結果CSV）
PIPELINE_CSV = "pipeline_products.csv"

# 進捗ファイルパス（--resume用）
PROGRESS_FILE = LOG_DIR / "listing_progress.json"


def setup_logging() -> None:
    """ロギングをファイル＋標準出力に設定する"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "auto_listing.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_progress() -> dict:
    """進捗ファイルを読み込む。存在しない場合は初期値を返す"""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"completed": [], "failed": []}


def save_progress(progress: dict) -> None:
    """進捗をJSONファイルに書き出す（クラッシュ対策）"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def _product_key(product: dict, index: int) -> str:
    """商品の一意キーを返す（handle → url → インデックスの優先順）"""
    return product.get("handle") or product.get("url") or f"product_{index}"


def run_pipeline(test_mode: bool = False, resume: bool = False) -> None:
    """メインパイプライン

    Args:
        test_mode: True の場合は最初の1件だけ出品する
        resume: True の場合は前回の続きから出品する
    """
    logger = logging.getLogger(__name__)
    csv_handler = CsvHandler()

    if resume:
        # ─────────────────────────────────────────────
        # 再開モード: スクレイピングをスキップして既存CSVを使用
        # ─────────────────────────────────────────────
        logger.info("再開モード: 既存データを読み込みます (%s)", PIPELINE_CSV)
        products = csv_handler.load_products(PIPELINE_CSV)
        if not products:
            logger.error(
                "再開用のCSVが見つかりません: %s\n"
                "先に通常実行 (--resumeなし) を行ってください。",
                CSV_OUTPUT_DIR / PIPELINE_CSV,
            )
            return

        progress = load_progress()
        completed_keys = set(progress.get("completed", []))
        pending_products = [
            p for i, p in enumerate(products)
            if _product_key(p, i) not in completed_keys
        ]
        logger.info(
            "再開: 全%d件 / 完了済み%d件 / 残り%d件",
            len(products),
            len(completed_keys),
            len(pending_products),
        )
        products = pending_products

        if not products:
            logger.info("すべての商品が出品済みです。")
            return

    else:
        # ─────────────────────────────────────────────
        # 通常モード: スクレイピング → 計算 → 翻訳 → CSV保存
        # ─────────────────────────────────────────────

        # Step 1: スクレイピング
        logger.info("=" * 60)
        logger.info("Step 1/4: baseblu.com からセール商品を取得中...")
        scraper = BasebluScraper()
        products = scraper.scrape_sale_products()
        if not products:
            logger.error("商品が取得できませんでした。ネットワーク接続を確認してください。")
            return
        logger.info("  -> %d件取得", len(products))

        # Step 2: 価格計算
        logger.info("Step 2/4: BUYMA販売価格を計算中...")
        calculator = PriceCalculator()
        products = [calculator.enrich_product_with_price(p) for p in products]
        logger.info("  -> 価格計算完了")

        # Step 3: 日本語テキスト生成
        logger.info("Step 3/4: 日本語テキストを生成中...")
        translator = TextTranslator()
        products = [translator.enrich_product_with_translations(p) for p in products]
        logger.info("  -> 翻訳完了")

        # Step 4準備: CSVに保存（--resumeで再利用できるようにする）
        csv_handler.save_products(products, filename=PIPELINE_CSV)
        logger.info("  -> %s に保存済み（再開用）", PIPELINE_CSV)

        # 進捗ファイルを新規作成（前回分をリセット）
        progress = {"completed": [], "failed": []}
        save_progress(progress)

    # ─────────────────────────────────────────────
    # テストモード: 最初の1件だけに絞る
    # ─────────────────────────────────────────────
    if test_mode:
        logger.info("テストモード: 最初の1件だけ出品します")
        products = products[:1]

    # ─────────────────────────────────────────────
    # Step 4: BUYMA出品
    # ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Step 4/4: BUYMA に出品中... （対象: %d件）", len(products))

    automation = BuymaAutomation()
    try:
        if not automation.start():
            logger.error("BUYMA へのログインに失敗しました。認証情報を確認してください。")
            return

        success_count = 0
        fail_count = 0

        for i, product in enumerate(products):
            key = _product_key(product, i)
            name = product.get("name_ja") or product.get("name") or key
            logger.info("[%d/%d] 出品中: %s", i + 1, len(products), name)

            listed = False
            if automation.navigate_to_exhibit():
                if automation.fill_product_form(product):
                    listed = automation.submit_listing()

            if listed:
                progress["completed"].append(key)
                success_count += 1
                logger.info("  -> 成功")
            else:
                progress["failed"].append(key)
                fail_count += 1
                logger.warning("  -> 失敗: %s", name)

            # 1件ごとに進捗を保存（クラッシュ時の再開用）
            save_progress(progress)

    finally:
        automation.close()

    # ─────────────────────────────────────────────
    # サマリー
    # ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("出品完了: %d件成功 / %d件失敗 / 計%d件", success_count, fail_count, len(products))
    if fail_count:
        logger.warning(
            "失敗した商品は %s に記録されています。\n"
            "  --resume で再実行すると失敗分を除いた未完了分から再開できます。",
            PROGRESS_FILE,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BUYMA 全商品一括出品スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使い方:
  python3 scripts/buyma_auto_listing.py          全商品を一括出品
  python3 scripts/buyma_auto_listing.py --test   まず1件だけ試す
  python3 scripts/buyma_auto_listing.py --resume 途中から再開
        """,
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="テストモード: 最初の1件だけ出品する",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="再開モード: 前回の続きから出品する（スクレイピングをスキップ）",
    )
    args = parser.parse_args()
    setup_logging()
    run_pipeline(test_mode=args.test, resume=args.resume)


if __name__ == "__main__":
    main()

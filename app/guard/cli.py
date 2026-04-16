"""
Guard CLI エントリポイント。

cron や手動実行で在庫監視を行う。

使い方:
    python3 -m app.guard.cli              # 全出品の在庫チェック
    python3 -m app.guard.cli --once       # 1 回だけ実行して終了
    python3 -m app.guard.cli --dry-run    # 停止・再出品の DB 更新を行わない

cron 設定例（1 日 2 回）:
    0 9,21 * * * cd ~/buyma_automation && python3 -m app.guard.cli >> logs/guard.log 2>&1
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_config
from app.core.models import Base
from app.guard.stock_monitor import StockMonitor

logger = logging.getLogger("guard")


def setup_logging(level: str = "INFO") -> None:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "guard.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Guard: 在庫監視")
    parser.add_argument("--once", action="store_true", help="1 回だけ実行")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 更新を行わない（チェック結果のみ表示）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    config = get_config()

    engine = create_engine(f"sqlite:///{config.db_path}", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        monitor = StockMonitor()
        logger.info("Guard starting...")
        summary = monitor.run_all(session)

        if args.dry_run:
            session.rollback()
            logger.info("DRY RUN — changes rolled back")
        else:
            session.commit()

        print(f"\n=== Guard 在庫チェック結果 ===")
        print(f"  チェック対象: {summary['total']} 件")
        print(f"  在庫あり:     {summary['available']} 件")
        print(f"  停止:         {summary['stopped']} 件")
        print(f"  再出品:       {summary['relisted']} 件")
        print(f"  エラー:       {summary['failed']} 件")

        if summary["stopped"] > 0:
            logger.warning(
                "%d listing(s) stopped due to stock unavailability",
                summary["stopped"],
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()

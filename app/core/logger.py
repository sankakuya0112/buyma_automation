"""統一ログシステム（JSON 形式ファイル出力 + コンソール出力）"""

import json
import logging
from datetime import datetime
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """ログを JSON 形式で出力するフォーマッター。"""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logger(
    name: str,
    log_dir: str = "logs",
    level: str = "INFO",
) -> logging.Logger:
    """
    標準化されたロガーをセットアップ。

    - ファイル出力: JSON 形式（{log_dir}/{name}.log）
    - コンソール出力: 人間が読める形式

    Args:
        name: ロガー名（= ログファイル名のベース）
        log_dir: ログ出力ディレクトリ
        level: ログレベル文字列

    Returns:
        設定済み Logger
    """
    logger = logging.getLogger(name)

    # 既にハンドラが設定されていれば重複追加しない
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # ファイルハンドラ（JSON 形式）
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(f"{log_dir}/{name}.log", encoding="utf-8")
    fh.setFormatter(JSONFormatter())
    logger.addHandler(fh)

    # コンソールハンドラ（人間用）
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(ch)

    return logger

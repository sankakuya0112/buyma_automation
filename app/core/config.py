"""設定管理（config.json + .env 読み込み）"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    """
    アプリケーション全体の設定を管理。
    config.json と環境変数から読み込む。環境変数が優先。
    """

    # BUYMA credentials
    buyma_email: str = ""
    buyma_password: str = ""

    # Browser
    headless: bool = True
    timeout_seconds: int = 30

    # Database
    db_path: str = "data/automation.db"

    # Scraping
    baseblu_search_url: str = "https://www.baseblu.com/en-us/collections/sales"
    baseblu_timeout: int = 20

    # Profit calculation
    target_margin_pct: float = 25.0
    min_profit_jpy: float = 3000.0

    # Logging
    log_level: str = "INFO"
    log_dir: str = "logs"

    # Guard
    guard_check_interval_hours: float = 12.0

    # Pricing
    jpy_exchange_rate: Optional[float] = None  # None → 自動取得

    @classmethod
    def from_file(cls, config_path: str = "config.json") -> "Config":
        """
        config.json と環境変数から設定を読み込む。
        ファイルが存在しない場合はデフォルト値を使用。
        """
        data: dict = {}
        config_file = Path(config_path)

        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

        # 環境変数で上書き
        data["buyma_email"] = os.getenv("BUYMA_EMAIL", data.get("buyma_email", ""))
        data["buyma_password"] = os.getenv("BUYMA_PASSWORD", data.get("buyma_password", ""))
        headless_env = os.getenv("HEADLESS")
        if headless_env is not None:
            data["headless"] = headless_env.lower() == "true"

        # Config dataclass に存在しないキーを除去
        valid_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_fields}

        return cls(**filtered)


_config_instance: Optional[Config] = None


def get_config(config_path: str = "config.json") -> Config:
    """グローバル設定インスタンスを取得（シングルトン）。"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config.from_file(config_path)
    return _config_instance


def reset_config() -> None:
    """テスト等でキャッシュをリセットする。"""
    global _config_instance
    _config_instance = None

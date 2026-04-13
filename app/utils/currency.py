"""為替レート取得（メモリキャッシュ付き・24時間有効）"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# フォールバック為替レート（API 取得失敗時）
_FALLBACK_RATES: dict[str, float] = {
    "EUR_JPY": 163.0,
    "USD_JPY": 150.0,
    "GBP_JPY": 190.0,
}


class CurrencyConverter:
    """
    複数通貨から日本円への換算。
    レート取得結果をメモリキャッシュ（24時間有効）。
    """

    def __init__(self) -> None:
        self._cache: dict[str, float] = {}
        self._cache_time: dict[str, datetime] = {}

    def get_rate(self, from_currency: str, to_currency: str = "JPY") -> float:
        """
        from_currency から to_currency へのレートを取得。
        キャッシュが有効（24時間以内）であればキャッシュを返す。
        API 取得失敗時はフォールバック値を使用。
        """
        cache_key = f"{from_currency}_{to_currency}"

        # キャッシュチェック
        if cache_key in self._cache:
            age = datetime.utcnow() - self._cache_time[cache_key]
            if age < timedelta(hours=24):
                return self._cache[cache_key]

        rate = self._fetch_rate(from_currency, to_currency)

        self._cache[cache_key] = rate
        self._cache_time[cache_key] = datetime.utcnow()
        return rate

    def _fetch_rate(self, from_currency: str, to_currency: str) -> float:
        """exchangerate-api.com から為替レートを取得する。"""
        try:
            response = requests.get(
                f"https://api.exchangerate-api.com/v4/latest/{from_currency}",
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()
            rate: Optional[float] = data.get("rates", {}).get(to_currency)
            if rate is not None:
                logger.debug("Fetched rate %s→%s: %.4f", from_currency, to_currency, rate)
                return float(rate)
        except Exception as exc:
            logger.warning("Failed to fetch exchange rate %s→%s: %s", from_currency, to_currency, exc)

        # フォールバック
        fallback_key = f"{from_currency}_{to_currency}"
        fallback = _FALLBACK_RATES.get(fallback_key, 1.0)
        logger.warning("Using fallback rate for %s: %.4f", fallback_key, fallback)
        return fallback

    def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str = "JPY",
    ) -> float:
        """amount を from_currency から to_currency に換算する。"""
        rate = self.get_rate(from_currency, to_currency)
        return amount * rate

    def clear_cache(self) -> None:
        """キャッシュをクリアする（テスト用）。"""
        self._cache.clear()
        self._cache_time.clear()


# モジュールレベルのシングルトン
currency = CurrencyConverter()

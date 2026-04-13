"""リトライデコレータ定義"""

import logging
import time
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 1.0,
):
    """
    関数の実行をリトライするデコレータ。

    Args:
        max_retries: 最大リトライ回数（初回実行は含まない）
        delay: 初回リトライ前の待機時間（秒）
        backoff: 待機時間の増加倍率（1.0 = 一定間隔）

    Example:
        @retry(max_retries=3, delay=2, backoff=2.0)
        def fetch_data():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if attempt < max_retries:
                        logger.warning(
                            "%s failed (attempt %d/%d): %s",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            exc,
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            "%s failed after %d attempts",
                            func.__name__,
                            max_retries + 1,
                        )

            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator

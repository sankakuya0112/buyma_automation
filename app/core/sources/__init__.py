"""仕入先 (Source) 抽象化レイヤ。

Phase 2c で導入。サイト固有のスクレイピング (`app.scouts`) と区別され、
ここでは「仕入先のメタデータ + CSV パイプラインのアダプタ」を提供する。

新仕入先 (Italist 等) を追加するときは:
  1. `app/core/sources/<name>.py` に `class <Name>Source(BaseSource)` を作る
  2. このファイルの `REGISTERED_SOURCES` に登録
  3. data/categories.json / brands.json に必要なら拡張
"""

from __future__ import annotations

from app.core.sources.base import BaseSource
from app.core.sources.baseblu import BasebluSource
from app.core.sources.italist import ItalistSource


REGISTERED_SOURCES: dict[str, type[BaseSource]] = {
    "baseblu": BasebluSource,
    "italist": ItalistSource,
    # 将来追加予定:
    # "farfetch": FarfetchSource,
}


def get_source(name: str) -> BaseSource:
    """source 名から BaseSource インスタンスを返す。未登録なら baseblu を default。"""
    key = (name or "").strip().lower() or "baseblu"
    cls = REGISTERED_SOURCES.get(key)
    if cls is None:
        # 未登録 source は baseblu に fallback (旧 CSV の透過処理)
        cls = REGISTERED_SOURCES["baseblu"]
    return cls()


__all__ = ["BaseSource", "BasebluSource", "REGISTERED_SOURCES", "get_source"]

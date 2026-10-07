"""仕入先 (Source) 抽象化レイヤ。

Phase 2c で導入。サイト固有のスクレイピング (scripts/*_sales_to_csv.py) と区別され、
ここでは「仕入先のメタデータ + CSV パイプラインのアダプタ」を提供する。

## 新しい仕入先を追加する 2 つの方法

1. **設定だけで追加する (推奨・Shopify サイト向け)**
   `data/sources.json` に 1 ブロック足すだけ。Python コードは不要。

       python3 scripts/shopify_sales_to_csv.py --source <キー名> --probe   # 取得可否の確認
       python3 scripts/shopify_sales_to_csv.py --source <キー名>           # CSV 生成
       python3 scripts/filter_baseblu_profitable.py --source <キー名>      # 利益計算

2. **専用クラスを書く (サイト固有の処理が要る場合)**
   - `app/core/sources/<name>.py` に `class <Name>Source(BaseSource)` を作る
   - 下の `REGISTERED_SOURCES` に登録
   - `tests/test_sources.py` にメタデータ検証テストを追加

`get_source()` は **専用クラス → data/sources.json** の順に解決する。
名前が空 (source_name 列の無い旧 CSV) のときだけ baseblu とみなし、
未登録・disabled の名前は ValueError (別の仕入先の原価体系で黙って計算しない)。
"""

from __future__ import annotations

from app.core.sources.base import BaseSource
from app.core.sources.baseblu import BasebluSource
from app.core.sources.config_source import (
    ConfigSource,
    available_source_names,
    get_source_config,
    load_source_configs,
)
from app.core.sources.italist import ItalistSource

DEFAULT_SOURCE_NAME = "baseblu"

REGISTERED_SOURCES: dict[str, type[BaseSource]] = {
    "baseblu": BasebluSource,
    "italist": ItalistSource,
    # 上記以外の仕入先は data/sources.json で定義する (ConfigSource)
}


def get_source(name: str) -> BaseSource:
    """source 名から BaseSource インスタンスを返す。

    解決順:
      1. 名前が空 → baseblu (source_name 列の無い旧 CSV の透過処理)
      2. `REGISTERED_SOURCES` の専用クラス (baseblu / italist)
      3. `data/sources.json` の設定 (ConfigSource)
      4. どれにも無い / disabled → ValueError
         (2026-10 以前は baseblu に黙って fallback しており、別の仕入先の商品を
          baseblu の通貨・送料・関税条件で計算してしまう危険があった)
    """
    key = (name or "").strip().lower() or DEFAULT_SOURCE_NAME

    cls = REGISTERED_SOURCES.get(key)
    if cls is not None:
        return cls()

    try:
        config = get_source_config(key)
    except ValueError:
        # 設定ファイルが壊れていても既存パイプラインは止めない。
        # 壊れた設定は scripts/shopify_sales_to_csv.py が明示的にエラーにする。
        config = None
    if config is not None:
        return ConfigSource(key, config)

    raise ValueError(
        f"仕入先 {name!r} は app/core/sources/ にも data/sources.json にもありません (または disabled)"
    )


def known_source_names() -> list[str]:
    """専用クラス + 設定ファイルの全仕入先名。"""
    names = set(REGISTERED_SOURCES) | set(available_source_names())
    return sorted(names)


__all__ = [
    "BaseSource",
    "BasebluSource",
    "ConfigSource",
    "ItalistSource",
    "REGISTERED_SOURCES",
    "DEFAULT_SOURCE_NAME",
    "available_source_names",
    "get_source",
    "get_source_config",
    "known_source_names",
    "load_source_configs",
]

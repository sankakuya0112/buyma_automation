"""outputs/reports 配下の日付付きレポートファイルを探す純粋関数。

ファイル名の規約: ``YYYY-MM-DD_<source>_<kind>`` (仕入先付き) または
``YYYY-MM-DD_<kind>`` (仕入先なし。例: ``2026-09-24_market_prices.json``)。

scripts/ 側で ``glob("*_baseblu_...")`` を書かず、必ずここを使う。
2026-09-24 以前は各スクリプトが baseblu 固定の glob を持っていたため、
他の仕入先で run_autopilot を回すと相場取得や AI 補強が baseblu の表を読んでいた。

同じ日に 2 つの仕入先を回した場合も、仕入先を指定すればその表だけを選ぶ。
未指定なら「最後に書かれたもの」(日付 → 更新時刻 → 名前の順) を選ぶ。
"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def report_glob(kind: str, source: str | None = None) -> str:
    """``kind`` (拡張子込み。例 ``"profitable_products.csv"``) の glob パターン。

    source を指定すると ``*_<source>_<kind>``、未指定なら ``*_<kind>`` (全仕入先)。
    """
    src = (source or "").strip().lower()
    return f"*_{src}_{kind}" if src else f"*_{kind}"


def _sort_key(path: str) -> tuple[str, float, str]:
    name = os.path.basename(path)
    m = _DATE_PREFIX.match(name)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    return (m.group(0) if m else "", mtime, name)


def list_reports(kind: str, source: str | None = None,
                 reports_dir: str | Path | None = None) -> list[str]:
    """該当するレポートのパスを古い順に返す。"""
    base = Path(reports_dir) if reports_dir else REPORTS_DIR
    files = glob.glob(str(base / report_glob(kind, source)))
    return sorted(files, key=_sort_key)


def latest_report(kind: str, source: str | None = None,
                  reports_dir: str | Path | None = None) -> str | None:
    """最新のレポートのパス。無ければ None。"""
    files = list_reports(kind, source, reports_dir)
    return files[-1] if files else None

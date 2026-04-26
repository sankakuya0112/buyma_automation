"""外部 EC ベンチマーク (Farfetch JP 等) との価格比較ユーティリティ。

Phase 2b で導入。BUYMA 内競合がゼロ/低いだけでは「独占して target 価格で
売れる」とは限らない。購入者は外部 EC (Farfetch / 公式 / 百貨店) と比較する
ため、「同等品が外部 EC で安く出ている商品」は SKIP すべき。

設計:
  1. 外部 EC を fetch するロジック (例: scripts/fetch_farfetch_benchmarks.py)
     → JSON ファイルに `{product_key: ExternalBenchmark}` 形式で保存
  2. このモジュールの load_benchmarks() で読み込み
  3. evaluate_external_benchmark(final_price, benchmark) で
     pass / warn / skip を判定
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class ExternalBenchmark:
    """外部 EC の同等商品ベンチマーク。"""

    source: str                         # "farfetch_jp" 等
    matched_url: Optional[str]
    matched_title: Optional[str]
    min_price_jpy: Optional[int]
    sample_count: int                   # 検索ヒット数 (0 = 完全に取れず)
    fetched_at: str                     # ISO 形式

    @classmethod
    def empty(cls, source: str = "farfetch_jp") -> "ExternalBenchmark":
        return cls(
            source=source,
            matched_url=None,
            matched_title=None,
            min_price_jpy=None,
            sample_count=0,
            fetched_at=datetime.utcnow().isoformat(),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ExternalBenchmark":
        return cls(
            source=data.get("source", "unknown"),
            matched_url=data.get("matched_url"),
            matched_title=data.get("matched_title"),
            min_price_jpy=data.get("min_price_jpy"),
            sample_count=int(data.get("sample_count", 0)),
            fetched_at=data.get("fetched_at", ""),
        )


# 外部優位の判定マージン (デフォルト: 自社売価が外部最安値より 10% 以上安いと pass)
DEFAULT_ADVANTAGE_MARGIN = 0.10


def evaluate_external_benchmark(
    final_price_jpy: int,
    benchmark: Optional[ExternalBenchmark],
    advantage_margin: float = DEFAULT_ADVANTAGE_MARGIN,
) -> tuple[str, str]:
    """外部ベンチマークと自社売価を比較する。

    Returns:
        (action, reason) のタプル。
        action: "pass" | "warn" | "skip"
        reason: "no_external_data" | "no_external_match" | "external_advantage" |
                "external_close" | "external_cheaper"
    """
    if benchmark is None:
        return "pass", "no_external_data"
    if benchmark.min_price_jpy is None or benchmark.sample_count == 0:
        # 外部にも在庫なし → 独占維持できる可能性あり
        return "pass", "no_external_match"

    threshold = benchmark.min_price_jpy * (1 - advantage_margin)
    if final_price_jpy <= threshold:
        return "pass", "external_advantage"
    if final_price_jpy <= benchmark.min_price_jpy:
        # 外部より安くはないがほぼ同等 → 出品はするが優位性薄
        return "warn", "external_close"
    return "skip", "external_cheaper"


def load_benchmarks(path: str) -> dict[str, ExternalBenchmark]:
    """JSON ファイルからベンチマークを読み込む。

    形式: {"PRODUCT_KEY": {"source": "...", "min_price_jpy": ..., ...}}
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {key: ExternalBenchmark.from_dict(value) for key, value in raw.items()}


def save_benchmarks(path: str, benchmarks: dict[str, ExternalBenchmark]) -> None:
    """JSON ファイルにベンチマークを保存する。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    serializable = {key: bench.to_dict() for key, bench in benchmarks.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def make_product_key(vendor: str, title: str, sku: str = "") -> str:
    """商品 key を生成する (vendor + title の英数字化)。

    BUYMA market fetch / Farfetch fetch / filter で同じ key を使い、
    ベンチマークを商品単位で紐付ける。
    """
    base = f"{vendor}_{title}"
    if sku:
        base = f"{base}_{sku}"
    # 英数字とアンダースコアのみに正規化
    safe = "".join(c if c.isalnum() else "_" for c in base.upper())
    # 連続アンダースコアを 1 つに
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_")[:120]

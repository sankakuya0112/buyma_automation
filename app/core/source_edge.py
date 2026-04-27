"""仕入先優位スコア (source_edge) — Phase 2c+ Milestone 1 stub。

複数仕入先を扱うようになったときに「同一製品で 2 番目に安い source との価格差」を
評価する。詳細設計は docs/strategy/SOURCE_EDGE_DESIGN.md 参照。

Milestone 1 (本ファイル) は dataclass + evaluator 関数のみ。source_index.json の
蓄積や自動切替は Milestone 2 以降。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class SourceEdgeStats:
    """同一製品 (canonical_key) について複数仕入先の landed cost を比較した結果。"""

    canonical_key: str
    cheapest_source: str
    cheapest_landed_cost_jpy: int
    second_cheapest_source: Optional[str] = None
    second_cheapest_landed_cost_jpy: Optional[int] = None
    n_sources: int = 1
    matched_at: str = ""

    @property
    def edge_jpy(self) -> int:
        """2 番目の仕入先との円換算価格差。比較対象なしなら 0。"""
        if self.second_cheapest_landed_cost_jpy is None:
            return 0
        return max(0, self.second_cheapest_landed_cost_jpy - self.cheapest_landed_cost_jpy)

    @property
    def edge_pct(self) -> float:
        """edge_jpy を cheapest_landed_cost_jpy で割った比率 (%)。"""
        if self.cheapest_landed_cost_jpy <= 0:
            return 0.0
        return round(self.edge_jpy / self.cheapest_landed_cost_jpy * 100, 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["edge_jpy"] = self.edge_jpy
        d["edge_pct"] = self.edge_pct
        return d


def evaluate_source_edge(
    edge: Optional[SourceEdgeStats],
    final_price_jpy: int,
    current_source: str = "",
    min_edge_jpy: int = 10000,
    min_edge_ratio: float = 0.05,
) -> tuple[str, str]:
    """source_edge から (action, reason) を決定する。

    Args:
        edge: 同一製品の SourceEdgeStats。None なら独占とみなす
        final_price_jpy: 出品予定の売価 (JPY)
        current_source: 現在出品しようとしている source の name (例 "baseblu")。
            指定があり edge.cheapest_source と異なれば skip する
        min_edge_jpy: edge の絶対閾値 (default ¥10,000)
        min_edge_ratio: edge の対売価比閾値 (default 5%)

    Returns:
        (action, reason):
          - ("pass", "exclusive_source")     比較対象なし
          - ("skip", "not_cheapest_source")  自分より安い source あり
          - ("warn", "low_source_edge")      edge が閾値未満
          - ("pass", "high_source_edge")     edge 十分
    """
    if edge is None or edge.n_sources <= 1:
        return "pass", "exclusive_source"

    if current_source and edge.cheapest_source and current_source.lower() != edge.cheapest_source.lower():
        return "skip", "not_cheapest_source"

    threshold = max(min_edge_jpy, int(final_price_jpy * min_edge_ratio))
    if edge.edge_jpy < threshold:
        return "warn", "low_source_edge"

    return "pass", "high_source_edge"

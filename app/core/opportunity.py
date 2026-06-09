"""商品機会スコア (opportunity score) — 期待値ベースの商品選別 (Phase 2d)。

従来の filter は「期待利益額」降順で出品候補を並べていたが、利益額が
大きくても売れなければ期待値はゼロ。本モジュールは

    opportunity_score = expected_profit_jpy × P(成約)

で「儲かりやすさ × 売れやすさ」を統合し、出品優先度を決める。

P(成約) は以下の需要シグナルから推定するヒューリスティック:

  1. BUYMA 競合密度 (market_sample_count)
     - 高競合 = 需要実証済み (最も強いシグナル)。price_leader で出すなら
       回転が速い
     - 競合ゼロ = 需要未検証。独占だが「誰も欲しがらない」リスクと裏腹
  2. 価格優位 (price_edge_ratio)
     - 相場中央値より何 % 安く出せるか。安いほど成約率が上がる
  3. 仕入元の消化率 (source sell-through)
     - baseblu 側でサイズが売れて消えている商品 = 現実の需要がある
       (全サイズ残 = 動いていない商品)
  4. BUYMA お気に入り数 (market_wish_total、取得できた場合のみ)

確率の絶対値は粗い仮定だが、**ランキング (相対順位) に使う**ため
一貫した単調性があれば十分。係数は運用実績で較正する。
"""

from __future__ import annotations

from dataclasses import dataclass

# 競合密度別の基礎月次成約確率 (仮定値)。
# 「高競合 = 需要実証済み」を反映して high が最も高い。
# none (競合ゼロ) は独占だが需要未検証のため低め。
BASE_SALE_PROBABILITY: dict[str, float] = {
    "none": 0.02,
    "low": 0.04,
    "medium": 0.07,
    "high": 0.12,
    "unknown": 0.03,
}

# 価格優位の効き (edge_ratio 1% ごとに確率 +2%)。クランプ上限 +100%。
EDGE_SENSITIVITY = 2.0
EDGE_RATIO_CLAMP = 0.5

# 仕入元消化率の効き (全サイズ売切間際なら +50%)
SELLTHROUGH_BOOST = 0.5

# お気に入り数の効き (100 件で +50%、それ以上は頭打ち)
WISH_BOOST_CAP = 0.5
WISH_SCALE = 100.0

# 確率クランプ (ヒューリスティックの暴走防止)
MIN_PROBABILITY = 0.005
MAX_PROBABILITY = 0.60


@dataclass
class DemandSignals:
    """1 商品の需要シグナル集合。取得できないものはデフォルトのまま渡す。"""

    market_sample_count: int = 0
    source_total_sizes: int = 0          # 仕入元の全サイズ数
    source_available_sizes: int = 0      # 仕入元の在庫ありサイズ数
    discount_rate: float = 0.0           # 仕入元の割引率 (%)
    market_wish_total: int = 0           # BUYMA 検索結果のお気に入り合計 (任意)

    @property
    def sellthrough(self) -> float:
        """仕入元での消化率 (0.0-1.0)。サイズ情報が無ければ 0。

        例: 全 5 サイズ中 2 サイズ残 → (5-2)/5 = 0.6
        """
        if self.source_total_sizes <= 0:
            return 0.0
        sold = self.source_total_sizes - self.source_available_sizes
        return max(0.0, min(1.0, sold / self.source_total_sizes))


def estimate_sale_probability(
    competition_level: str,
    price_edge_ratio: float = 0.0,
    signals: DemandSignals | None = None,
) -> float:
    """月次成約確率のヒューリスティック推定。

    Args:
        competition_level: decide_final_price の competition_level
            ('none' | 'low' | 'medium' | 'high' | 'unknown')
        price_edge_ratio: (相場中央値 - 自社売価) / 相場中央値。
            相場情報が無い場合は 0.0 を渡す。負値 (相場より高い) も許容。
        signals: 需要シグナル。None なら競合密度と edge のみで推定。

    Returns:
        0.005-0.60 にクランプされた確率。
    """
    base = BASE_SALE_PROBABILITY.get(competition_level, BASE_SALE_PROBABILITY["unknown"])

    # 価格優位: 相場より安いほど成約率が上がる。相場より高ければ下がる。
    edge = max(-EDGE_RATIO_CLAMP, min(EDGE_RATIO_CLAMP, price_edge_ratio))
    edge_factor = 1.0 + EDGE_SENSITIVITY * edge

    sellthrough_factor = 1.0
    wish_factor = 1.0
    if signals is not None:
        sellthrough_factor = 1.0 + SELLTHROUGH_BOOST * signals.sellthrough
        if signals.market_wish_total > 0:
            wish_factor = 1.0 + min(
                WISH_BOOST_CAP, signals.market_wish_total / WISH_SCALE * WISH_BOOST_CAP
            )

    p = base * edge_factor * sellthrough_factor * wish_factor
    return max(MIN_PROBABILITY, min(MAX_PROBABILITY, p))


def opportunity_score(expected_profit_jpy: float, sale_probability: float) -> int:
    """期待値 (円) = 期待利益 × 成約確率。出品優先度のソートキー。"""
    if expected_profit_jpy <= 0:
        return 0
    return int(round(expected_profit_jpy * sale_probability))


def price_edge_ratio(market_median_jpy: float | None, final_price_jpy: float | None) -> float:
    """相場中央値に対する価格優位率。情報不足なら 0.0。"""
    try:
        median = float(market_median_jpy or 0)
        final = float(final_price_jpy or 0)
    except (TypeError, ValueError):
        return 0.0
    if median <= 0 or final <= 0:
        return 0.0
    return (median - final) / median


def count_sizes(sizes_csv: str) -> int:
    """CSV の sizes / available_sizes 列 ('36, 38, 40') からサイズ数を数える。"""
    if not sizes_csv or not str(sizes_csv).strip():
        return 0
    return len([t for t in str(sizes_csv).split(",") if t.strip()])

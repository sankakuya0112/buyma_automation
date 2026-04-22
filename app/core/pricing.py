"""
統一された利益計算モジュール。

PROFIT_FIRST タスク 1-1 の実装。BUYMA 出品価格を算出する唯一の関数群。

計算に含める要素:
    - VAT 還付（欧州サイト: 仕入値の約 16.7%）
    - 国際送料（商品重量 × 単価、または固定値）
    - 輸入関税（カテゴリ別マスタ）
    - 輸入消費税（10%）
    - BUYMA 手数料（5.8%）
    - 決済手数料（3%）
    - 目標利益率

使用例:
    from app.core.pricing import PricingParams, calculate_pricing

    params = PricingParams(source_price=100.0, currency="EUR", category="bag")
    result = calculate_pricing(params)
    print(result.selling_price_jpy, result.profit_jpy)

なお既存の `filter_baseblu_profitable.py` / `draft_builder._calculate_listing_price`
/ `run_pipeline._calculate_profit` は本モジュールに置き換えられる予定。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# 定数・マスタ
# ---------------------------------------------------------------------------

BUYMA_COMMISSION_RATE = 0.058         # BUYMA 手数料（5.8%）
PAYMENT_COMMISSION_RATE = 0.030       # 決済手数料（3.0%）
CONSUMPTION_TAX_RATE = 0.10           # 輸入消費税 10%
DEFAULT_VAT_REFUND_RATE = 0.167       # EU 域外輸出の VAT 還付 16.7%
DEFAULT_TARGET_MARGIN_PCT = 0.25      # 目標利益率 25%
DEFAULT_EXCHANGE_RATES: dict[str, float] = {
    "EUR": 163.0,
    "USD": 150.0,
    "GBP": 190.0,
    "JPY": 1.0,
}

# 国際送料（重量 × 単価）簡易マスタ
SHIPPING_RATE_JPY_PER_KG = 3000.0

# カテゴリ別重量（kg）。不明なものは DEFAULT_WEIGHT。
DEFAULT_WEIGHT_KG: dict[str, float] = {
    "bag": 1.2,
    "handbag": 1.0,
    "shoulder bag": 1.2,
    "tote bag": 1.3,
    "clutch": 0.6,
    "backpack": 1.5,
    "wallet": 0.3,
    "belt": 0.3,
    "dress": 0.7,
    "coat": 1.8,
    "jacket": 1.4,
    "sweater": 0.8,
    "cardigan": 0.8,
    "t-shirt": 0.3,
    "shirt": 0.4,
    "blouse": 0.4,
    "pants": 0.7,
    "trousers": 0.7,
    "jeans": 0.9,
    "skirt": 0.5,
    "sneakers": 1.2,
    "boots": 1.6,
    "sandals": 0.9,
    "loafers": 1.1,
    "pumps": 1.0,
    "shoes": 1.2,
    "scarf": 0.2,
    "sunglasses": 0.2,
    "watch": 0.3,
    "jewelry": 0.1,
    "hat": 0.3,
    "cap": 0.3,
}
DEFAULT_WEIGHT = 1.0

# カテゴリ別関税率マスタ（簡易版・日本の輸入関税）
# 厳密には HS コード別のため、必要に応じて上書きすること。
DEFAULT_DUTY_RATES: dict[str, float] = {
    # 衣類（織物）
    "dress": 0.091,
    "shirt": 0.091,
    "blouse": 0.091,
    "pants": 0.091,
    "trousers": 0.091,
    "skirt": 0.091,
    "jacket": 0.091,
    "coat": 0.091,
    "jumpsuit": 0.091,
    "suit": 0.091,
    "jeans": 0.091,
    "swimwear": 0.091,
    "lingerie": 0.091,
    "underwear": 0.091,
    # 衣類（ニット）
    "sweater": 0.109,
    "cardigan": 0.109,
    "t-shirt": 0.109,
    # バッグ・革製品
    "bag": 0.08,
    "handbag": 0.08,
    "shoulder bag": 0.08,
    "tote bag": 0.08,
    "clutch": 0.08,
    "backpack": 0.08,
    "wallet": 0.08,
    "belt": 0.08,
    # 靴
    "sneakers": 0.08,
    "boots": 0.17,
    "sandals": 0.08,
    "loafers": 0.17,
    "pumps": 0.17,
    "shoes": 0.10,
    # アクセサリー
    "scarf": 0.07,
    "sunglasses": 0.05,
    "watch": 0.0,
    "jewelry": 0.05,
    "hat": 0.08,
    "cap": 0.08,
    "gloves": 0.08,
    "socks": 0.07,
}
DEFAULT_DUTY_RATE = 0.10  # マスタに無いカテゴリのフォールバック


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------

@dataclass
class PricingParams:
    """価格計算の入力。"""

    source_price: float                             # 現地通貨の仕入値
    currency: str = "EUR"                           # 仕入通貨
    category: str = ""                              # カテゴリ（関税・重量の参照キー）
    weight_kg: Optional[float] = None               # None → マスタから推定
    exchange_rate: Optional[float] = None           # None → DEFAULT_EXCHANGE_RATES
    vat_refund_rate: float = DEFAULT_VAT_REFUND_RATE
    duty_rate: Optional[float] = None               # None → マスタから推定
    target_margin_pct: float = DEFAULT_TARGET_MARGIN_PCT
    shipping_jpy: Optional[float] = None            # None → 重量 × 単価
    buyma_commission_rate: float = BUYMA_COMMISSION_RATE
    payment_commission_rate: float = PAYMENT_COMMISSION_RATE
    consumption_tax_rate: float = CONSUMPTION_TAX_RATE


@dataclass
class PricingResult:
    """価格計算の結果。"""

    # 仕入関連（全て円換算）
    source_price_jpy: float                         # 現地仕入値の円換算
    vat_refund_jpy: float                           # VAT 還付額
    shipping_jpy: float                             # 国際送料
    customs_jpy: float                              # 輸入関税
    consumption_tax_jpy: float                      # 輸入消費税
    total_cost_jpy: float                           # 総仕入原価

    # 販売関連
    selling_price_jpy: int                          # 推奨販売価格（100円切上げ）
    buyma_commission_jpy: float                     # BUYMA 手数料
    payment_commission_jpy: float                   # 決済手数料
    profit_jpy: float                               # 手数料差引後の純利益
    margin_pct: float                               # 利益率（total_cost 比、%）

    # 使用した中間値
    exchange_rate: float
    duty_rate: float
    weight_kg: float

    def is_profitable(self, min_profit_jpy: float = 3000.0) -> bool:
        """利益額が閾値を超えているか。"""
        return self.profit_jpy >= min_profit_jpy


# ---------------------------------------------------------------------------
# 市場連動価格決定 (Phase 2a)
# ---------------------------------------------------------------------------

# 最低利益ライン: max(MIN_PROFIT_FLOOR_JPY, MIN_PROFIT_FLOOR_PCT × 売価)
MIN_PROFIT_FLOOR_JPY = 5000           # 絶対額の下限 (¥5,000)
MIN_PROFIT_FLOOR_PCT = 0.05           # 売価比の下限 (5%)
MARKET_POSITION_DISCOUNT = 0.05       # 相場中央値から下げる割合 (5% 安く)
MIN_MARKET_SAMPLES = 3                # 相場判定に必要な最低件数


@dataclass
class MarketStats:
    """BUYMA 市場相場の統計値。`fetch_buyma_market_prices.py` の出力を流し込む。"""

    sample_count: int = 0                            # 取得した出品件数
    median_jpy: Optional[int] = None                 # 売価中央値
    min_jpy: Optional[int] = None                    # 最安値
    max_jpy: Optional[int] = None                    # 最高値

    def is_reliable(self, min_samples: int = MIN_MARKET_SAMPLES) -> bool:
        """中央値を信頼に足る件数が揃っているか。"""
        return self.sample_count >= min_samples and self.median_jpy is not None


@dataclass
class FinalPriceDecision:
    """最終価格決定の結果。"""

    action: str                                       # 'list' | 'skip'
    reason: str                                       # スキップ/採用理由 (例: 'below_breakeven', 'market_aware', 'no_market_data')
    final_price_jpy: Optional[int]                    # 最終売価 (skip 時 None)
    target_price_jpy: int                             # 25% 利益率での目標売価
    breakeven_price_jpy: int                          # 原価 + 最低利益 floor を満たす最低売価
    floor_profit_jpy: int                             # 適用された最低利益額
    market_median_jpy: Optional[int] = None
    market_sample_count: int = 0
    expected_profit_jpy: int = 0                      # 最終売価で見込まれる純利益
    expected_margin_pct: float = 0.0                  # 最終売価での利益率


def _profit_at_price(
    selling_price_jpy: int,
    total_cost_jpy: float,
    buyma_commission_rate: float,
    payment_commission_rate: float,
) -> float:
    """指定売価での純利益を計算する (手数料控除後)。"""
    fees = selling_price_jpy * (buyma_commission_rate + payment_commission_rate)
    return selling_price_jpy - fees - total_cost_jpy


def _floor_profit(selling_price_jpy: int) -> int:
    """売価に応じた最低利益ライン: max(¥5000, 売価×5%)。"""
    pct_floor = selling_price_jpy * MIN_PROFIT_FLOOR_PCT
    return int(max(MIN_PROFIT_FLOOR_JPY, pct_floor))


def _round_up_100(value: float) -> int:
    """100 円単位切り上げ。"""
    return int(math.ceil(value / 100) * 100)


def _solve_breakeven_price(
    total_cost_jpy: float,
    buyma_commission_rate: float,
    payment_commission_rate: float,
) -> int:
    """floor 利益 (max ¥5000, 5%) を確保する最低売価を求める。

    数式: price - price × fees - cost ≥ max(5000, 0.05 × price)

    ケース 1 (5% > ¥5000 つまり price ≥ 100,000):
        price × (1 - fees - 0.05) ≥ cost
        → price = cost / (1 - fees - 0.05)
    ケース 2 (¥5000 > 5% つまり price < 100,000):
        price × (1 - fees) ≥ cost + 5000
        → price = (cost + 5000) / (1 - fees)
    両方を計算し、辻褄が合う方 (= floor 制約を実際に満たす方) を採用。
    """
    fees = buyma_commission_rate + payment_commission_rate
    # case 1
    p1 = _round_up_100(total_cost_jpy / max(1 - fees - MIN_PROFIT_FLOOR_PCT, 0.01))
    # case 2
    p2 = _round_up_100((total_cost_jpy + MIN_PROFIT_FLOOR_JPY) / max(1 - fees, 0.01))
    # case 1 が成立するのは p1 ≥ 100,000 のとき (5% 制約が支配)
    if p1 >= int(MIN_PROFIT_FLOOR_JPY / MIN_PROFIT_FLOOR_PCT):
        return p1
    return p2


def decide_final_price(
    pricing_result: PricingResult,
    market: Optional[MarketStats] = None,
    buyma_commission_rate: float = BUYMA_COMMISSION_RATE,
    payment_commission_rate: float = PAYMENT_COMMISSION_RATE,
) -> FinalPriceDecision:
    """市場相場と原価下限を踏まえて最終売価を決定する。

    決定ロジック:
      1. 原価下限 breakeven_price = 最低利益 floor を満たす最低売価
      2. 目標売価 target_price = pricing_result.selling_price_jpy (25% 利益率)
      3. 市場データ無し: target を採用 (= 従来挙動)
      4. 市場データあり:
         - 候補売価 = max(中央値 × (1 - 5%), breakeven)
         - 候補売価が breakeven を満たすか確認 → 満たさない/中央値そのものが
           breakeven 未満 → skip (below_breakeven)
         - 満たす → final = min(候補売価, target × 1.5) ※ 上限ガード
                                                          相場が高くても上値追いしすぎない
    """
    target_price = pricing_result.selling_price_jpy
    cost = pricing_result.total_cost_jpy
    breakeven_price = _solve_breakeven_price(
        cost, buyma_commission_rate, payment_commission_rate
    )
    floor_at_target = _floor_profit(target_price)

    # 市場データ無し → target を採用 (target が breakeven を満たすか確認)
    if market is None or not market.is_reliable():
        if target_price < breakeven_price:
            # 25% 利益率でも floor を割る = 計算ロジック異常 (通常起こらない)
            return FinalPriceDecision(
                action="skip",
                reason="target_below_breakeven",
                final_price_jpy=None,
                target_price_jpy=target_price,
                breakeven_price_jpy=breakeven_price,
                floor_profit_jpy=floor_at_target,
                market_median_jpy=market.median_jpy if market else None,
                market_sample_count=market.sample_count if market else 0,
            )
        profit = _profit_at_price(target_price, cost, buyma_commission_rate, payment_commission_rate)
        margin = (profit / cost * 100) if cost > 0 else 0
        return FinalPriceDecision(
            action="list",
            reason="no_market_data",
            final_price_jpy=target_price,
            target_price_jpy=target_price,
            breakeven_price_jpy=breakeven_price,
            floor_profit_jpy=floor_at_target,
            market_median_jpy=market.median_jpy if market else None,
            market_sample_count=market.sample_count if market else 0,
            expected_profit_jpy=int(round(profit)),
            expected_margin_pct=round(margin, 2),
        )

    # 市場データあり
    market_aware_price = _round_up_100(market.median_jpy * (1 - MARKET_POSITION_DISCOUNT))
    if market_aware_price < breakeven_price:
        # 相場 -5% でも breakeven を割る → 出品しても赤字 → skip
        return FinalPriceDecision(
            action="skip",
            reason="below_breakeven",
            final_price_jpy=None,
            target_price_jpy=target_price,
            breakeven_price_jpy=breakeven_price,
            floor_profit_jpy=_floor_profit(market_aware_price),
            market_median_jpy=market.median_jpy,
            market_sample_count=market.sample_count,
        )

    # 市場価格 -5% を採用するが、target × 1.5 を上限とする (相場が異常に高い場合の安全弁)
    upper_cap = _round_up_100(target_price * 1.5)
    final_price = min(market_aware_price, upper_cap)
    profit = _profit_at_price(final_price, cost, buyma_commission_rate, payment_commission_rate)
    margin = (profit / cost * 100) if cost > 0 else 0
    return FinalPriceDecision(
        action="list",
        reason="market_aware",
        final_price_jpy=final_price,
        target_price_jpy=target_price,
        breakeven_price_jpy=breakeven_price,
        floor_profit_jpy=_floor_profit(final_price),
        market_median_jpy=market.median_jpy,
        market_sample_count=market.sample_count,
        expected_profit_jpy=int(round(profit)),
        expected_margin_pct=round(margin, 2),
    )


# ---------------------------------------------------------------------------
# マスタ解決ヘルパー
# ---------------------------------------------------------------------------

def resolve_duty_rate(
    category: str,
    rates: dict[str, float] = DEFAULT_DUTY_RATES,
) -> float:
    """カテゴリ名から関税率を決定する。"""
    if not category:
        return DEFAULT_DUTY_RATE
    key = category.lower().strip()
    if key in rates:
        return rates[key]
    # 部分一致（"leather bag" → "bag" にヒット等）
    for keyword, rate in rates.items():
        if keyword in key:
            return rate
    return DEFAULT_DUTY_RATE


def resolve_weight(
    category: str,
    weights: dict[str, float] = DEFAULT_WEIGHT_KG,
) -> float:
    """カテゴリ名から想定重量（kg）を決定する。"""
    if not category:
        return DEFAULT_WEIGHT
    key = category.lower().strip()
    if key in weights:
        return weights[key]
    for keyword, weight in weights.items():
        if keyword in key:
            return weight
    return DEFAULT_WEIGHT


def resolve_exchange_rate(currency: str) -> float:
    """通貨から為替レート（対JPY）を取得する。"""
    return DEFAULT_EXCHANGE_RATES.get(currency.upper(), 1.0)


# ---------------------------------------------------------------------------
# メインの計算関数
# ---------------------------------------------------------------------------

def calculate_pricing(params: PricingParams) -> PricingResult:
    """
    BUYMA 出品価格と利益を算出する。

    計算フロー:
        1. VAT 還付後の仕入値（円）= source × exchange × (1 - vat_refund)
        2. 国際送料（円）       = 重量 × 単価 または指定値
        3. 輸入関税（円）       = (仕入値 + 送料) × 関税率
        4. 輸入消費税（円）     = (仕入値 + 送料 + 関税) × 10%
        5. 総仕入原価（円）     = 仕入値 + 送料 + 関税 + 消費税
        6. 売価（円）           = 原価 × (1 + 目標利益率) / (1 - 手数料率合計)
                                  → 100 円単位に切り上げ
        7. 実利益（円）         = 売価 - 手数料 - 原価

    Args:
        params: 計算入力

    Returns:
        計算結果（販売価格・利益・中間値を含む）

    Raises:
        ValueError: 手数料合計が 99% 以上
    """
    exchange_rate = params.exchange_rate or resolve_exchange_rate(params.currency)
    duty_rate = params.duty_rate if params.duty_rate is not None else resolve_duty_rate(params.category)
    weight_kg = params.weight_kg if params.weight_kg is not None else resolve_weight(params.category)
    shipping_jpy = (
        params.shipping_jpy
        if params.shipping_jpy is not None
        else weight_kg * SHIPPING_RATE_JPY_PER_KG
    )

    commission_total = params.buyma_commission_rate + params.payment_commission_rate
    if commission_total >= 0.99:
        raise ValueError(
            f"Commission rates too high: {commission_total:.2%}"
        )

    # 1. 仕入値（VAT還付前後）
    source_price_jpy = params.source_price * exchange_rate
    vat_refund_jpy = source_price_jpy * params.vat_refund_rate
    net_source_jpy = source_price_jpy - vat_refund_jpy

    # 2-4. 税関コスト
    customs_jpy = (net_source_jpy + shipping_jpy) * duty_rate
    consumption_tax_jpy = (net_source_jpy + shipping_jpy + customs_jpy) * params.consumption_tax_rate

    # 5. 総原価
    total_cost_jpy = net_source_jpy + shipping_jpy + customs_jpy + consumption_tax_jpy

    # 6. 売価（手数料を含めた逆算・100円切上）
    raw_price = total_cost_jpy * (1 + params.target_margin_pct) / (1 - commission_total)
    selling_price_jpy = int(math.ceil(raw_price / 100) * 100)

    # 7. 利益確定
    buyma_commission_jpy = selling_price_jpy * params.buyma_commission_rate
    payment_commission_jpy = selling_price_jpy * params.payment_commission_rate
    revenue_after_fees = selling_price_jpy - buyma_commission_jpy - payment_commission_jpy
    profit_jpy = revenue_after_fees - total_cost_jpy
    margin_pct = (profit_jpy / total_cost_jpy * 100) if total_cost_jpy > 0 else 0.0

    return PricingResult(
        source_price_jpy=round(source_price_jpy, 2),
        vat_refund_jpy=round(vat_refund_jpy, 2),
        shipping_jpy=round(shipping_jpy, 2),
        customs_jpy=round(customs_jpy, 2),
        consumption_tax_jpy=round(consumption_tax_jpy, 2),
        total_cost_jpy=round(total_cost_jpy, 2),
        selling_price_jpy=selling_price_jpy,
        buyma_commission_jpy=round(buyma_commission_jpy, 2),
        payment_commission_jpy=round(payment_commission_jpy, 2),
        profit_jpy=round(profit_jpy, 2),
        margin_pct=round(margin_pct, 2),
        exchange_rate=exchange_rate,
        duty_rate=duty_rate,
        weight_kg=weight_kg,
    )

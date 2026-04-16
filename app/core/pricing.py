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

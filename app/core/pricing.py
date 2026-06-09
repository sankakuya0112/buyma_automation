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
import os
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# 定数・マスタ
# ---------------------------------------------------------------------------

BUYMA_COMMISSION_RATE = 0.077         # BUYMA 成約手数料 (一般出品者 7.7%)
PAYMENT_COMMISSION_RATE = 0.0         # 決済システム利用料は購入者負担のため 0
BANK_TRANSFER_FEE_JPY = 330.0         # 振込手数料 (220-385 の中央値)
CONSUMPTION_TAX_RATE = 0.10           # 輸入消費税 10%
DEFAULT_VAT_REFUND_RATE = 0.167       # EU 域外輸出の VAT 還付 16.7%
DEFAULT_TARGET_MARGIN_PCT = 0.25      # 目標利益率 25%

# 為替レートはデフォルトを 2026-04-23 ECB 参考値にアップデート。
# 実運用では .env の EUR_TO_JPY / USD_TO_JPY / GBP_TO_JPY で月次上書き可。
DEFAULT_EXCHANGE_RATES: dict[str, float] = {
    "EUR": 186.0,   # 2026-04-23 ECB 参考 (旧 163.0 から 14% 改訂)
    "USD": 160.0,
    "GBP": 210.0,
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
    # 仕入先の関税負担方式
    #   "DDU": 商品価格に関税・輸入消費税が含まれず、日本到着時に別途課税
    #          → 関税・輸入消費税を加算 (Baseblu, FRMODA 等)
    #   "DDP": チェックアウト価格に関税・輸入税込み (Italist, Tessabit, Antonioli 等)
    #          → 関税・消費税は加算しない (二重計上を防ぐ)
    landed_cost_basis: str = "DDU"
    shipping_jpy: Optional[float] = None            # None → 重量 × 単価
    buyma_commission_rate: float = BUYMA_COMMISSION_RATE
    payment_commission_rate: float = PAYMENT_COMMISSION_RATE
    consumption_tax_rate: float = CONSUMPTION_TAX_RATE
    # 海外決済手数料 (クレジットカードの海外事務手数料 ~2.2%)。
    # 外貨建て仕入れで必ず発生するが従来モデルでは未計上だった。
    # default 0.0 で後方互換。Source.get_pricing_params() が実値を注入する。
    purchase_fx_fee_rate: float = 0.0
    # 国内発送費 (BUYMA 出品者→購入者、送料込み出品が前提)。
    # default 0.0 で後方互換。Source.get_pricing_params() が実値を注入する。
    domestic_shipping_jpy: float = 0.0


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
    landed_cost_basis: str = "DDU"                  # "DDU" or "DDP"
    purchase_fx_fee_jpy: float = 0.0                # 海外決済手数料 (円)
    domestic_shipping_jpy: float = 0.0              # 国内発送費 (円)

    def is_profitable(self, min_profit_jpy: float = 3000.0) -> bool:
        """利益額が閾値を超えているか。"""
        return self.profit_jpy >= min_profit_jpy


# ---------------------------------------------------------------------------
# 市場連動価格決定 (Phase 2a)
# ---------------------------------------------------------------------------

# 最低利益ライン: カテゴリ別に絶対額と売価比を併用する。
# 基準: 自社発送 + 返品自己負担 (アパレル/シューズはサイズ起因の返品率が高い)
CATEGORY_FLOORS: dict[str, tuple[int, float]] = {
    # (絶対額 JPY, 売価比)
    "CLOTHING": (10000, 0.08),
    "FOOTWEAR": (10000, 0.08),
    "BAGS":     (8000,  0.06),
    "ACCESSORIES": (5000, 0.05),
}
DEFAULT_CATEGORY_FLOOR = (5000, 0.05)   # 未知カテゴリ

# 後方互換 (既存テスト/呼出で使用しているため残す。新規呼出は CATEGORY_FLOORS 経由)
MIN_PROFIT_FLOOR_JPY = 5000
MIN_PROFIT_FLOOR_PCT = 0.05

MARKET_POSITION_DISCOUNT = 0.05       # 相場中央値から下げる割合 (5% 安く)
MIN_MARKET_SAMPLES = 3                # 相場判定に必要な最低件数
UNRELIABLE_MARKET_COST_RATIO = 0.7    # 市場 median がこの比率 × 原価未満なら偽相場として無視
                                      # (Phase 2b で 0.5→0.7 引上げ。BUYMA default 商品混入を広めに捕捉)

# 競合密度戦略 (Phase 2a Tier 2)
HIGH_COMPETITION_THRESHOLD = 10       # サンプル >= この値 → 高競合として SKIP
LOW_COMPETITION_THRESHOLD = 1         # サンプル <= この値 → 低競合として target 採用


@dataclass
class MarketStats:
    """BUYMA 市場相場の統計値。`fetch_buyma_market_prices.py` の出力を流し込む。"""

    sample_count: int = 0                            # 取得した出品件数
    median_jpy: Optional[int] = None                 # 売価中央値
    min_jpy: Optional[int] = None                    # 最安値
    max_jpy: Optional[int] = None                    # 最高値
    # ブランド一致信頼度 (0.0-1.0)。fetch 側で raw_n のうち
    # 明確に他ブランドだった件数を控除した比率。default=1.0 で後方互換。
    brand_match_confidence: float = 1.0

    def is_reliable(self, min_samples: int = MIN_MARKET_SAMPLES) -> bool:
        """中央値を信頼に足る件数が揃っているか。

        brand_match_confidence が 0.5 未満なら他ブランド混入と判断し False。
        """
        return (
            self.sample_count >= min_samples
            and self.median_jpy is not None
            and self.brand_match_confidence >= 0.5
        )


@dataclass
class FinalPriceDecision:
    """最終価格決定の結果。"""

    action: str                                       # 'list' | 'skip'
    reason: str                                       # スキップ/採用理由
    final_price_jpy: Optional[int]                    # 最終売価 (skip 時 None)
    target_price_jpy: int                             # 25% 利益率での目標売価
    breakeven_price_jpy: int                          # 原価 + 最低利益 floor を満たす最低売価
    floor_profit_jpy: int                             # 適用された最低利益額
    market_median_jpy: Optional[int] = None
    market_sample_count: int = 0
    expected_profit_jpy: int = 0                      # 最終売価で見込まれる純利益
    expected_margin_pct: float = 0.0                  # 最終売価での利益率
    competition_level: str = "unknown"                # 'none' | 'low' | 'medium' | 'high' | 'unknown'


def _profit_at_price(
    selling_price_jpy: int,
    total_cost_jpy: float,
    buyma_commission_rate: float,
    payment_commission_rate: float,
) -> float:
    """指定売価での純利益を計算する (手数料控除後)。"""
    fees = selling_price_jpy * (buyma_commission_rate + payment_commission_rate)
    return selling_price_jpy - fees - total_cost_jpy


def _resolve_floor_params(category: str) -> tuple[int, float]:
    """カテゴリから (絶対額, 売価比) を解決する。"""
    if not category:
        return DEFAULT_CATEGORY_FLOOR
    key = category.strip().upper()
    if key in CATEGORY_FLOORS:
        return CATEGORY_FLOORS[key]
    # 部分一致 (例: "CLOTHING_WOMEN" → CLOTHING)
    for k, v in CATEGORY_FLOORS.items():
        if k in key:
            return v
    return DEFAULT_CATEGORY_FLOOR


def _floor_profit(selling_price_jpy: int, category: str = "") -> int:
    """カテゴリ別の最低利益ラインを返す。

    CLOTHING/FOOTWEAR: max(¥10,000, 売価×8%)
    BAGS:              max(¥8,000,  売価×6%)
    ACCESSORIES/他:    max(¥5,000,  売価×5%)
    """
    floor_abs, floor_pct = _resolve_floor_params(category)
    pct_floor = selling_price_jpy * floor_pct
    return int(max(floor_abs, pct_floor))


def _round_up_100(value: float) -> int:
    """100 円単位切り上げ。"""
    return int(math.ceil(value / 100) * 100)


def _solve_breakeven_price(
    total_cost_jpy: float,
    buyma_commission_rate: float,
    payment_commission_rate: float,
    category: str = "",
) -> int:
    """カテゴリ別 floor 利益を確保する最低売価を求める。

    数式: price - price × fees - cost ≥ max(floor_abs, floor_pct × price)

    ケース 1 (% が支配): price × (1 - fees - floor_pct) ≥ cost
        → price = cost / (1 - fees - floor_pct)
    ケース 2 (絶対額が支配): price × (1 - fees) ≥ cost + floor_abs
        → price = (cost + floor_abs) / (1 - fees)
    両方を計算し、実際に floor 制約を満たすほうを採用する。
    """
    floor_abs, floor_pct = _resolve_floor_params(category)
    fees = buyma_commission_rate + payment_commission_rate
    denom_pct = max(1 - fees - floor_pct, 0.01)
    denom_abs = max(1 - fees, 0.01)
    # case 1
    p1 = _round_up_100(total_cost_jpy / denom_pct)
    # case 2
    p2 = _round_up_100((total_cost_jpy + floor_abs) / denom_abs)
    # % 制約が支配するのは、その price で % 制約値が floor_abs 以上のとき
    crossover = int(floor_abs / floor_pct) if floor_pct > 0 else 0
    if p1 >= crossover:
        return p1
    return p2


def _categorize_competition(sample_count: int) -> str:
    """サンプル数から競合密度ラベルを返す。"""
    if sample_count <= 0:
        return "none"
    if sample_count <= LOW_COMPETITION_THRESHOLD:
        return "low"
    if sample_count >= HIGH_COMPETITION_THRESHOLD:
        return "high"
    return "medium"


def decide_final_price(
    pricing_result: PricingResult,
    market: Optional[MarketStats] = None,
    buyma_commission_rate: float = BUYMA_COMMISSION_RATE,
    payment_commission_rate: float = PAYMENT_COMMISSION_RATE,
    category: str = "",
) -> FinalPriceDecision:
    """低競合戦略を軸に最終売価を決定する (Phase 2a Tier 2)。

    戦略:
      1. 競合ゼロ/低 (n ≤ 1)  → target 採用: 独占チャンスで強気
      2. 高競合 (n ≥ 10)      → SKIP: 新規アカウントの価格競争は不利
      3. 偽相場 (median < 原価 × 50%) → ブティック系の BUYMA デフォルト表示扱いで
                                          target 採用 (competition_level は none)
      4. 中競合で相場が原価割れ → SKIP (below_breakeven)
      5. 中競合で正常相場    → target vs (中央値 -5%) の高い方、上限 target × 1.5

    引数 `category` は floor 金額決定 + 最終判定の文脈に使う。
    """
    target_price = pricing_result.selling_price_jpy
    cost = pricing_result.total_cost_jpy
    breakeven_price = _solve_breakeven_price(
        cost, buyma_commission_rate, payment_commission_rate, category=category,
    )
    floor_at_target = _floor_profit(target_price, category=category)
    competition = _categorize_competition(market.sample_count if market else 0)

    # 偽相場ガード: 市場 median が原価の 50% 未満 = BUYMA デフォルト商品を拾っている
    # 疑い濃厚。ブティック系ブランドで発生しがち。market を None 扱いにして
    # target を採用する。competition は "none" として扱う。
    fake_market = False
    if (
        market is not None
        and market.median_jpy
        and cost > 0
        and market.median_jpy < cost * UNRELIABLE_MARKET_COST_RATIO
    ):
        fake_market = True
        market = None
        competition = "none"

    def _build_list_decision(final: int, reason: str) -> FinalPriceDecision:
        profit = _profit_at_price(
            final, cost, buyma_commission_rate, payment_commission_rate,
        )
        margin = (profit / cost * 100) if cost > 0 else 0
        return FinalPriceDecision(
            action="list",
            reason=reason,
            final_price_jpy=final,
            target_price_jpy=target_price,
            breakeven_price_jpy=breakeven_price,
            floor_profit_jpy=_floor_profit(final, category=category),
            market_median_jpy=market.median_jpy if market else None,
            market_sample_count=market.sample_count if market else 0,
            expected_profit_jpy=int(round(profit)),
            expected_margin_pct=round(margin, 2),
            competition_level=competition,
        )

    def _build_skip_decision(reason: str) -> FinalPriceDecision:
        return FinalPriceDecision(
            action="skip",
            reason=reason,
            final_price_jpy=None,
            target_price_jpy=target_price,
            breakeven_price_jpy=breakeven_price,
            floor_profit_jpy=floor_at_target,
            market_median_jpy=market.median_jpy if market else None,
            market_sample_count=market.sample_count if market else 0,
            competition_level=competition,
        )

    # --- 1. 市場データ無し / 偽相場 / サンプル極少 ---
    if market is None or not market.is_reliable() or competition in ("none", "low"):
        if target_price < breakeven_price:
            return _build_skip_decision("target_below_breakeven")
        reason = (
            "fake_market" if fake_market
            else ("low_competition" if competition == "low" else "no_market_data")
        )
        return _build_list_decision(target_price, reason)

    # --- 2. 高競合 ---
    if competition == "high":
        return _build_skip_decision("high_competition")

    # --- 3. 中競合 ---
    market_aware_price = _round_up_100(market.median_jpy * (1 - MARKET_POSITION_DISCOUNT))
    if market_aware_price < breakeven_price:
        return _build_skip_decision("below_breakeven")

    # target と market_aware_price の高いほう (上限 target × 1.5)
    upper_cap = _round_up_100(target_price * 1.5)
    chosen = max(target_price, market_aware_price)
    final_price = min(chosen, upper_cap)
    return _build_list_decision(final_price, "market_aware")


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
    """通貨から為替レート（対JPY）を取得する。

    優先順位:
      1. 環境変数 ``{CURRENCY}_TO_JPY`` (例: EUR_TO_JPY)
      2. ``DEFAULT_EXCHANGE_RATES`` マスタ
      3. 1.0 (デフォルト)
    """
    cur = currency.upper()
    env_key = f"{cur}_TO_JPY"
    env_val = os.getenv(env_key)
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return DEFAULT_EXCHANGE_RATES.get(cur, 1.0)


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

    # 1b. 海外決済手数料 (カード会社の海外事務手数料)。
    # 課金額ベース = チェックアウト総額に掛かるが、保守的に商品価格全額
    # (VAT 還付前) に適用する。還付が後日でもカード請求は満額のため。
    purchase_fx_fee_jpy = source_price_jpy * params.purchase_fx_fee_rate

    # 2-4. 税関コスト
    # DDP の場合: チェックアウト価格に関税・輸入消費税が含まれているため
    #             二重計上を防ぐためゼロ扱い
    # DDU の場合: 日本到着時に別途課税されるため通常通り計算
    basis = (params.landed_cost_basis or "DDU").upper()
    if basis == "DDP":
        customs_jpy = 0.0
        consumption_tax_jpy = 0.0
    else:
        customs_jpy = (net_source_jpy + shipping_jpy) * duty_rate
        consumption_tax_jpy = (net_source_jpy + shipping_jpy + customs_jpy) * params.consumption_tax_rate

    # 5. 総原価 (振込手数料も原価に含める: BUYMA → ショッパー入金時に差し引かれる)
    total_cost_jpy = (
        net_source_jpy + shipping_jpy + customs_jpy + consumption_tax_jpy
        + purchase_fx_fee_jpy + params.domestic_shipping_jpy
        + BANK_TRANSFER_FEE_JPY
    )

    # 6. 売価（手数料を含めた逆算・100円切上）
    raw_price = total_cost_jpy * (1 + params.target_margin_pct) / (1 - commission_total)
    selling_price_jpy = int(math.ceil(raw_price / 100) * 100)

    # 7. 利益確定
    buyma_commission_jpy = selling_price_jpy * params.buyma_commission_rate
    # payment_commission_jpy は 0 (購入者負担) だが後方互換でカラム保持し
    # 代わりに振込手数料を表示用に入れる
    payment_commission_jpy = (
        selling_price_jpy * params.payment_commission_rate
        if params.payment_commission_rate > 0 else BANK_TRANSFER_FEE_JPY
    )
    revenue_after_fees = selling_price_jpy - buyma_commission_jpy - (
        selling_price_jpy * params.payment_commission_rate
    )
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
        landed_cost_basis=basis,
        purchase_fx_fee_jpy=round(purchase_fx_fee_jpy, 2),
        domestic_shipping_jpy=round(params.domestic_shipping_jpy, 2),
    )

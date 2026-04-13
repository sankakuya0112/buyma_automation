"""出品データ生成（タイトル・説明・価格計算）"""

import logging
from dataclasses import dataclass, field
from typing import List

from sqlalchemy.orm import Session

from app.core.models import RankedProduct, SourceProduct
from app.utils.currency import currency
from app.utils.text import generate_buyma_title, normalize_text, translate_description

logger = logging.getLogger(__name__)

# BUYMA 手数料率（5.8%）
_BUYMA_COMMISSION_RATE = 0.058


@dataclass
class ListingDraft:
    """出品用下書きデータ。"""

    title: str
    description: str
    price_jpy: float
    image_urls: List[str]  # image_urls[0] がメイン、残りはサブ（最大 5 枚）
    sku: str
    brand: str
    color: str
    category: str


def build_draft(session: Session, ranked_product_id: int) -> ListingDraft:
    """
    RankedProduct から出品用 ListingDraft を生成する。

    Args:
        session: SQLAlchemy セッション
        ranked_product_id: 対象の RankedProduct.id

    Returns:
        ListingDraft インスタンス
    """
    ranked = session.get(RankedProduct, ranked_product_id)
    if ranked is None:
        raise ValueError(f"RankedProduct {ranked_product_id} not found")

    product: SourceProduct = ranked.source_product

    # タイトル生成（SEO 最適化）
    title = generate_buyma_title(
        brand=product.brand,
        product_name=product.title,
        sku=product.sku or "",
        color=product.color or None,
    )

    # 説明文生成（仕入れ先名・現地価格は非公開）
    description = _generate_description(product)

    # 価格計算
    price_jpy = _calculate_listing_price(product, ranked)

    # 画像（メイン 1 + サブ最大 5 = 最大 6 枚）
    image_urls: List[str] = (product.image_urls or [])[:6]
    if not image_urls:
        logger.warning("No images for product %d", product.id)

    draft = ListingDraft(
        title=title,
        description=description,
        price_jpy=price_jpy,
        image_urls=image_urls,
        sku=product.sku or "",
        brand=product.brand,
        color=product.color or "",
        category=product.category or "",
    )

    logger.info("Built draft for product %d: %s...", product.id, title[:50])
    return draft


def _calculate_listing_price(
    product: SourceProduct,
    ranked: RankedProduct,
) -> float:
    """
    BUYMA 出品価格（円）を算出する。

    計算式:
        cost_jpy = (source_price + shipping_cost) * exchange_rate
        listing_price = cost_jpy * (1 + target_margin) / (1 - commission_rate)
        → 100 円単位に切り上げ

    est_profit_jpy が既に算出されている場合はそれを使用する。
    """
    import math

    try:
        from app.core.config import get_config
        config = get_config()
        target_margin = config.target_margin_pct / 100
    except Exception:
        target_margin = 0.25

    exchange_rate = currency.get_rate(product.currency, "JPY")
    cost_jpy = (product.source_price + product.shipping_cost) * exchange_rate
    raw_price = cost_jpy * (1 + target_margin) / (1 - _BUYMA_COMMISSION_RATE)

    return math.ceil(raw_price / 100) * 100


def _generate_description(product: SourceProduct) -> str:
    """
    BUYMA 出品用説明文を生成する。

    仕様:
    - 仕入れ先名・現地価格は非公開
    - 英語説明文を（可能であれば）日本語に変換して掲載
    - フォーマットは固定テンプレートに準拠
    """
    translated = translate_description(product.description_en or "")

    details = (
        "===============================\n"
        f"{translated}\n"
        "\n"
        "【商品詳細】\n"
        f"ブランド: {product.brand}\n"
        f"SKU: {product.sku or 'N/A'}\n"
        f"色: {product.color or 'N/A'}\n"
        "\n"
        "【配送・取扱い】\n"
        "買付地: イタリア（ヨーロッパ）\n"
        "配送地: 日本\n"
        "関税・送料: 出品者負担\n"
        "購入期限: 90日\n"
        "==============================="
    )

    return normalize_text(details)

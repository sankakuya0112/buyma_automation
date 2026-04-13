"""出品前チェック（Governor ルール適用）"""

import logging
from typing import Tuple

from sqlalchemy.orm import Session

from app.core.models import RankedProduct
from app.governors.rules import GovernorRules

logger = logging.getLogger(__name__)


def run_preflight(
    session: Session,
    ranked_product_id: int,
) -> Tuple[bool, str]:
    """
    出品前チェックを実施する。Governor ルールを適用して結果を DB に保存する。

    Args:
        session: SQLAlchemy セッション
        ranked_product_id: チェック対象の RankedProduct.id

    Returns:
        (passed: bool, message: str)
        passed=True の場合のみ出品処理に進む。
    """
    ranked = session.get(RankedProduct, ranked_product_id)
    if ranked is None:
        msg = f"RankedProduct {ranked_product_id} not found"
        logger.error(msg)
        return False, msg

    product = ranked.source_product
    governor = GovernorRules(session)
    decision, reason = governor.evaluate(product, ranked)

    ranked.governor_decision = decision
    ranked.governor_notes = reason
    session.commit()

    if decision != "approved":
        logger.warning("Preflight failed for product %d: %s", product.id, reason)
        return False, reason

    logger.info("Preflight passed for product %d", product.id)
    return True, "OK"

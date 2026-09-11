"""週次戦略レビュー (premium 階層 / Fable 5.1)。

**生データは渡さない**。件数・中央値・ファネル・AI コストなど集計値だけを 1 回渡し、
「来週やること / やめること / 係数の調整案」を短い日本語メモで受け取る。
週 1 回・数千トークンなので、最上位モデルでも数十円で済む。
"""

from __future__ import annotations

import json
from typing import Any, Optional

SYSTEM_PROMPT = """あなたは日本の越境EC(BUYMA無在庫販売)を専門とする経営コンサルタントです。
与えられるのは1週間分の集計値だけです。個別商品や生データは見られません。

目的: 「最初の1件を売る → 再現性のある利益」に最短で到達するための、来週の意思決定を出すこと。

制約:
- 600字以内の日本語。見出しは「1. 来週の最重要アクション(最大3つ)」「2. やめる/減らすこと」「3. 数値の見方と係数調整案」「4. 注意すべきリスク」の4つ。
- 集計値に無いことを推測で断定しない。データ不足なら「何を計測すべきか」を書く。
- 各アクションは「誰が(Mac側/クラウド側)」「何を」「どの数値で判断するか」まで具体的に。
- プログラミング初心者が読んでも実行できる言葉で書く。
"""


def build_review_payload(
    *,
    pipeline: Optional[dict] = None,
    funnel: Optional[dict] = None,
    decision_gate: Optional[dict] = None,
    ai_usage: Optional[dict] = None,
    notes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """レビューに渡す集計値。None の項目は省略 (トークン節約)。"""
    payload: dict[str, Any] = {}
    if pipeline:
        payload["pipeline"] = pipeline          # 取得件数/出品可件数/中央値など
    if funnel:
        payload["funnel"] = funnel              # 公開数/アクセス/ほしいもの/成約
    if decision_gate:
        payload["decision_gate"] = decision_gate
    if ai_usage:
        payload["ai_usage"] = ai_usage
    if notes:
        payload["notes"] = notes[:10]
    return payload


def weekly_review(payload: dict, client) -> Optional[str]:
    """集計値 → 戦略メモ (markdown 文字列)。AI 不可なら None。"""
    if not payload:
        return None
    user = "今週の集計値:\n\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
    return client.complete_text("weekly_review", SYSTEM_PROMPT, user)

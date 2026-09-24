"""出品候補の審査 (standard 階層 / Sonnet 5)。

利益フィルタ (決定論) を通過した候補の **上位 N 件だけ** を渡し、
規約リスク・売れにくさ・データ品質の観点で list / hold / skip と優先度を付ける。
skip は明確な規約リスクのみ。迷いは hold (人間が管理画面で確認)。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from app.ai.router import policy_for

VERDICTS = ("list", "hold", "skip")
RISK_FLAGS = (
    "restricted_material",          # ワニ・ヘビ・トカゲ等 CITES 対象素材、毛皮
    "restricted_category",          # 化粧品・食品・医療機器・電波機器 など BUYMA/輸入規制
    "price_too_high_for_new_account",
    "market_price_below_ours",      # 相場中央値が自社売価より明確に安い
    "size_missing",                 # 衣類/靴でサイズ情報が無い
    "season_stale",                 # 2 年以上前のシーズン品
    "data_quality",                 # タイトル/説明が不十分、色不明 など
    "low_demand_signal",            # 競合ゼロかつ需要シグナル無し
    "other",
)

SYSTEM_PROMPT = """あなたはBUYMA(日本の越境ECモール)で無在庫販売を行うショップのマーチャンダイザーです。
利益計算と相場チェックを通過した出品候補について、「出品してよいか」「人が確認すべきか」「出してはいけないか」を審査します。

## 判定 (verdict)
- skip: 明確な規約・法令リスクがある場合のみ。例: ワニ革・パイソン・トカゲ革・毛皮などCITES/輸入規制素材、化粧品・食品・医薬部外品、電波法対象機器、明らかな偽物/コピー品の疑い。
- hold: 出品はできそうだが人が管理画面で確認した方がよい。例: 新規アカウントで販売価格が¥100,000超、相場中央値が自社売価より15%%以上安い、衣類/靴なのにサイズ情報が無い、2年以上前のシーズン品、タイトル/説明が不十分。
- list: 上記以外。利益・需要シグナルが揃っていれば優先度を高くする。

## 優先度 (priority) 1〜5
5=今すぐ出す(期待値高・リスク低) … 1=後回し。opportunity_score(期待値)、expected_margin_pct、competition_level(high=需要実証済み)、price_edge_ratio(相場より安い率)を重視。

## 出力
各候補について id / verdict / risk_flags(該当なしなら空配列) / reason(60文字以内、日本語) / priority を返す。
risk_flags は次の値のみ: %s
判断できない項目は推測せず、data_quality を付けて hold にする。
""" % ", ".join(RISK_FLAGS)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "risk_flags": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "priority": {"type": "integer"},
                },
                "required": ["id", "verdict", "risk_flags", "reason", "priority"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

_NUMERIC_FIELDS = (
    "final_price_jpy", "selling_price_jpy", "expected_profit_jpy", "expected_margin_pct",
    "market_median_jpy", "market_sample_count", "sale_probability", "opportunity_score",
    "price_edge_ratio", "discount_rate",
)


def _num(v):
    try:
        if v in ("", None):
            return None
        f = float(v)
        return int(f) if f.is_integer() else round(f, 4)
    except (TypeError, ValueError):
        return None


def compact_candidate(row: dict, pid: str) -> dict:
    out = {
        "id": pid,
        "brand": (row.get("vendor") or "").strip(),
        "title": (row.get("title") or "").strip()[:120],
        "product_type": (row.get("product_type") or "").strip(),
        "season": (row.get("season") or "").strip(),
        "sizes": (row.get("sizes") or "").strip()[:60],
        "available_sizes": (row.get("available_sizes") or "").strip()[:60],
        "competition_level": (row.get("competition_level") or "").strip(),
        "decision_reason": (row.get("decision_reason") or "").strip(),
        "description_excerpt": (row.get("description_en") or "").strip()[:200],
    }
    for f in _NUMERIC_FIELDS:
        v = _num(row.get(f))
        if v is not None:
            out[f] = v
    return out


def judge_candidates(rows: list[dict], client, ids: Optional[list[str]] = None,
                     today: Optional[date] = None) -> dict[str, dict]:
    """{id: {verdict, risk_flags, reason, priority}}。AI 不可時は空 dict。"""
    if not rows:
        return {}
    if ids is None:
        ids = [str(r.get("sku") or f"row{i}") for i, r in enumerate(rows)]
    policy = policy_for("judge")
    today = today or date.today()
    results: dict[str, dict] = {}
    for start in range(0, len(rows), policy.items_per_call):
        chunk = rows[start:start + policy.items_per_call]
        chunk_ids = ids[start:start + policy.items_per_call]
        payload = [compact_candidate(r, pid) for r, pid in zip(chunk, chunk_ids)]
        # 日付は system ではなく user 側に置く (system の prompt cache を壊さない)
        user = (
            f"本日: {today.isoformat()}。新規アカウント (販売実績なし) の前提で審査してください。\n\n"
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        data = client.complete_json("judge", SYSTEM_PROMPT, user, OUTPUT_SCHEMA)
        if not data or not isinstance(data.get("items"), list):
            continue
        for item in data["items"]:
            pid = str(item.get("id") or "")
            if pid not in chunk_ids:
                continue
            verdict = str(item.get("verdict") or "hold")
            if verdict not in VERDICTS:
                verdict = "hold"
            flags = [str(f) for f in (item.get("risk_flags") or []) if str(f) in RISK_FLAGS]
            try:
                priority = max(1, min(5, int(item.get("priority") or 3)))
            except (TypeError, ValueError):
                priority = 3
            results[pid] = {
                "verdict": verdict,
                "risk_flags": flags,
                "reason": str(item.get("reason") or "").strip()[:120],
                "priority": priority,
            }
    return results

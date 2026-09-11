"""モデルルーター — タスクごとに「どのモデルを・どれだけの出力で」使うかを決める。

ここだけを見れば「何にいくら払うか」が分かる状態を保つこと。
環境変数で上書き可能:
    AI_MODEL_CHEAP / AI_MODEL_STANDARD / AI_MODEL_PREMIUM   … 階層ごとのモデル ID
    AI_TASK_<TASK>_TIER (例: AI_TASK_JUDGE_TIER=cheap)        … タスク単位の階層変更
    USD_TO_JPY                                               … コスト換算レート
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# 階層とデフォルトモデル
# ---------------------------------------------------------------------------

TIER_CHEAP = "cheap"
TIER_STANDARD = "standard"
TIER_PREMIUM = "premium"
TIERS = (TIER_CHEAP, TIER_STANDARD, TIER_PREMIUM)

DEFAULT_MODELS: dict[str, str] = {
    TIER_CHEAP: "claude-haiku-4-5",      # 高速・最安。翻訳/分類などの量産タスク
    TIER_STANDARD: "claude-sonnet-5",    # 判断が要るが週数回の中量タスク
    TIER_PREMIUM: "claude-fable-5-1",    # 週 1 回の戦略判断。集計値のみ渡す
}

# USD / 1M tokens: (input, output, cache_write, cache_read)
# 出典: claude-api スキルの料金表 (2026-06 時点)。変更時はここだけ直す。
MODEL_PRICES_USD: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 6.25, 0.50),
    "claude-fable-5": (10.00, 50.00, 12.50, 1.00),
    "claude-fable-5-1": (10.00, 50.00, 12.50, 0.25),
}
_UNKNOWN_MODEL_PRICE = (5.00, 25.00, 6.25, 0.50)   # 未知モデルは Opus 相当で保守的に見積る


# ---------------------------------------------------------------------------
# タスク別ポリシー
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskPolicy:
    """1 種類の AI タスクに対する実行ポリシー。"""

    task: str
    tier: str
    max_tokens: int            # 出力上限 (JSON が途中で切れない範囲で小さく)
    effort: Optional[str]      # None → 省略 (Haiku は effort 非対応)
    items_per_call: int        # 1 リクエストにまとめる商品数 (system prompt の再送を減らす)
    cache_system: bool         # system prompt に prompt cache のブレークポイントを置くか
    description: str


TASK_POLICIES: dict[str, TaskPolicy] = {
    "listing_copy": TaskPolicy(
        task="listing_copy", tier=TIER_CHEAP, max_tokens=8000, effort=None,
        items_per_call=8, cache_system=True,
        description="英語商品情報 → BUYMA 用の日本語タイトル・説明文・検索キーワード",
    ),
    "category": TaskPolicy(
        task="category", tier=TIER_CHEAP, max_tokens=1500, effort=None,
        items_per_call=20, cache_system=True,
        description="キーワード辞書で決まらなかった商品の BUYMA 3 階層カテゴリ選択 (番号で回答)",
    ),
    "judge": TaskPolicy(
        task="judge", tier=TIER_STANDARD, max_tokens=6000, effort="medium",
        items_per_call=20, cache_system=True,
        description="利益フィルタ通過済み候補の出品可否・リスク・優先度の審査",
    ),
    "diagnose": TaskPolicy(
        task="diagnose", tier=TIER_STANDARD, max_tokens=3000, effort="medium",
        items_per_call=1, cache_system=False,
        description="Mac 実走ログの障害診断 (原因・対処手順の提案)",
    ),
    "weekly_review": TaskPolicy(
        task="weekly_review", tier=TIER_PREMIUM, max_tokens=4000, effort="high",
        items_per_call=1, cache_system=False,
        description="週次の集計値から次の一手を決める戦略レビュー (週 1 回まで)",
    ),
}


def policy_for(task: str) -> TaskPolicy:
    """タスク名からポリシーを返す。環境変数 AI_TASK_<TASK>_TIER で階層を上書きできる。"""
    base = TASK_POLICIES.get(task)
    if base is None:
        raise KeyError(f"unknown AI task: {task}")
    override = os.getenv(f"AI_TASK_{task.upper()}_TIER", "").strip().lower()
    if override and override in TIERS and override != base.tier:
        # dataclass は frozen なので replace で複製
        from dataclasses import replace
        return replace(base, tier=override)
    return base


def resolve_model(tier: str) -> str:
    """階層 → モデル ID。環境変数 AI_MODEL_<TIER> で上書き可能。"""
    if tier not in TIERS:
        raise KeyError(f"unknown AI tier: {tier}")
    env = os.getenv(f"AI_MODEL_{tier.upper()}", "").strip()
    return env or DEFAULT_MODELS[tier]


def supports_effort(model: str) -> bool:
    """output_config.effort を受け付けるモデルか (Haiku 4.5 は 400 になる)。"""
    return not model.startswith("claude-haiku")


def is_fable(model: str) -> bool:
    """Fable 系 (思考常時 ON / 拒否時フォールバック推奨) か。"""
    return model.startswith("claude-fable") or model.startswith("claude-mythos")


# ---------------------------------------------------------------------------
# コスト見積
# ---------------------------------------------------------------------------

def price_table(model: str) -> tuple[float, float, float, float]:
    return MODEL_PRICES_USD.get(model, _UNKNOWN_MODEL_PRICE)


def estimate_cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """usage からドル建てコストを見積る。input_tokens は非キャッシュ分のみ (API 仕様)。"""
    p_in, p_out, p_cw, p_cr = price_table(model)
    usd = (
        (input_tokens or 0) * p_in
        + (output_tokens or 0) * p_out
        + (cache_creation_input_tokens or 0) * p_cw
        + (cache_read_input_tokens or 0) * p_cr
    ) / 1_000_000.0
    return round(usd, 6)


def usd_to_jpy_rate() -> float:
    """コスト換算用の USD/JPY。.env の USD_TO_JPY → pricing のデフォルト → 160。"""
    env = os.getenv("USD_TO_JPY", "").strip()
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    try:
        from app.core.pricing import DEFAULT_EXCHANGE_RATES
        return float(DEFAULT_EXCHANGE_RATES.get("USD", 160.0))
    except Exception:  # pragma: no cover - pricing が無い環境
        return 160.0


def usd_to_jpy(usd: float) -> float:
    return round(usd * usd_to_jpy_rate(), 2)


def describe_policies() -> list[dict]:
    """ドキュメント/CLI 表示用: タスク → 階層 → モデル → 料金の一覧。"""
    rows = []
    for name in TASK_POLICIES:
        pol = policy_for(name)
        model = resolve_model(pol.tier)
        p_in, p_out, _, _ = price_table(model)
        rows.append({
            "task": name,
            "tier": pol.tier,
            "model": model,
            "max_tokens": pol.max_tokens,
            "effort": pol.effort or "-",
            "items_per_call": pol.items_per_call,
            "usd_per_mtok_in": p_in,
            "usd_per_mtok_out": p_out,
            "description": pol.description,
        })
    return rows

"""
ai_cost_report.py — AI (Claude API) の使用量・費用と、モデル使い分けの設定を表示する
--------------------------------------------------------------------------
    python3 scripts/ai_cost_report.py            # 直近 7 日
    python3 scripts/ai_cost_report.py --days 30
    python3 scripts/ai_cost_report.py --policy   # タスク → モデルの割り当て表だけ
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:  # pragma: no cover
    pass

from app.ai.client import DEFAULT_WEEKLY_BUDGET_JPY, UsageLedger  # noqa: E402
from app.ai.router import describe_policies, usd_to_jpy  # noqa: E402


def print_policy_table() -> None:
    print("🧭 モデル使い分け (環境変数 AI_MODEL_* / AI_TASK_*_TIER で変更可)")
    print(f"   {'task':14s} {'tier':9s} {'model':20s} {'$/Mtok in/out':14s} {'effort':7s} 説明")
    for r in describe_policies():
        print(f"   {r['task']:14s} {r['tier']:9s} {r['model']:20s} "
              f"{r['usd_per_mtok_in']:>5.2f}/{r['usd_per_mtok_out']:<6.2f}  {r['effort']:7s} {r['description']}")


def print_usage(days: int) -> None:
    import os
    ledger = UsageLedger()
    s = ledger.summarize(days)
    budget = float(os.getenv("AI_WEEKLY_BUDGET_JPY", DEFAULT_WEEKLY_BUDGET_JPY) or DEFAULT_WEEKLY_BUDGET_JPY)
    print(f"💴 AI 使用量 (直近 {days} 日): {s['calls']} 呼出 (キャッシュ命中 {s['cached_calls']}) "
          f"= ${s['total_usd']:.4f} ≈ ¥{s['total_jpy']:,.1f}")
    print(f"   週間予算: ¥{budget:,.0f} / 直近 7 日の消費: ¥{ledger.spent_jpy(7):,.1f}")
    if s["by_task"]:
        print("   タスク別:")
        for task, b in sorted(s["by_task"].items(), key=lambda kv: -kv[1]["cost_usd"]):
            print(f"     {task:14s} {b['calls']:4d} 回  in {b['input_tokens']:>8,} / out {b['output_tokens']:>7,} tok"
                  f"  ≈¥{usd_to_jpy(b['cost_usd']):,.1f}")
    if s["by_model"]:
        print("   モデル別:")
        for model, b in sorted(s["by_model"].items(), key=lambda kv: -kv[1]["cost_usd"]):
            print(f"     {model:22s} {b['calls']:4d} 回  ≈¥{usd_to_jpy(b['cost_usd']):,.1f}")
    if not s["calls"]:
        print("   (記録なし。AI 補強を実行すると data/ai_usage.jsonl に記録されます)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AI 使用量レポート")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--policy", action="store_true", help="割り当て表のみ表示")
    args = parser.parse_args(argv)
    print_policy_table()
    if not args.policy:
        print()
        print_usage(args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())

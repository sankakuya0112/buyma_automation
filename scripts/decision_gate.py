"""
decision_gate.py
----------------
週次の意思決定ゲート: スプリントの公開実績 + ファネル実測を突き合わせ、
事前コミット済みの基準 (app/core/decision_gate.py) で次の一手を判定する。

「もう少し様子を見る」「もう少し作り込む」という無期限判断を排除し、
継続 / 露出改善 / 価格・品質改定 / 量産解禁 のどれかを機械的に返す。

使い方:
    python3 scripts/decision_gate.py               # 判定
    python3 scripts/decision_gate.py --sales 1     # 成約数を手動指定 (実測より優先)
    python3 scripts/decision_gate.py --json        # 機械可読出力

データソース:
    data/first_sale_sprint.json  … 公開済み商品と published_at (分母)
    data/funnel_history.json     … アクセス/ほしいもの/売切ステータス (実測)
    どちらも無ければ「まず何をすべきか」を案内して終了する。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core import funnel  # noqa: E402
from app.core.decision_gate import GateVerdict, evaluate_gate  # noqa: E402
from app.core.first_sale import SprintManifest, elapsed_days  # noqa: E402

MANIFEST_PATH = PROJECT_ROOT / "data" / "first_sale_sprint.json"
HISTORY_PATH = PROJECT_ROOT / "data" / "funnel_history.json"

SOLD_STATUSES = ("売り切れ", "売切れ", "SOLD", "取引中")


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def gather(as_of: datetime, sales_override: int | None) -> tuple[GateVerdict, dict]:
    raw = load_json(MANIFEST_PATH)
    if raw is None:
        print("❌ スプリント未生成です。閉ループの起点から始めてください:")
        print("   python3 scripts/first_sale_sprint.py")
        sys.exit(1)
    manifest = SprintManifest.from_dict(raw)
    published = manifest.published_items()

    history = load_json(HISTORY_PATH) or {"snapshots": []}
    latest = funnel.latest_metrics_by_item(history)

    published_ids = [it.item_id for it in published if it.item_id]
    as_of_days = {
        it.item_id: elapsed_days(it.published_at, as_of)
        for it in published
        if it.item_id
    }

    weekly_access = None
    total_access = 0
    total_wish = 0
    observed_sales = 0
    if history["snapshots"] and published_ids:
        weekly_access = funnel.weekly_access_rates(history, published_ids, as_of_days)
        for iid in published_ids:
            m = latest.get(iid)
            if not m:
                continue
            total_access += m.get("access", 0)
            total_wish += m.get("wish", 0)
            if m.get("status") in SOLD_STATUSES:
                observed_sales += 1
        if not weekly_access:
            weekly_access = None  # funnel はあるがスプリント商品が未検出

    if sales_override is not None:
        observed_sales = sales_override

    verdict = evaluate_gate(
        published,
        as_of=as_of,
        observed_sales=observed_sales,
        weekly_access=weekly_access,
        total_access=total_access,
        total_wish=total_wish,
    )
    context = {
        "sprint_created_at": manifest.created_at,
        "published": len(published),
        "total_items": len(manifest.items),
        "funnel_snapshots": len(history["snapshots"]),
    }
    return verdict, context


def print_verdict(verdict: GateVerdict, context: dict) -> None:
    print("=" * 64)
    print(verdict.headline)
    print("=" * 64)
    print(f"スプリント: {context['sprint_created_at']} / "
          f"公開 {context['published']}/{context['total_items']} 件 / "
          f"ファネル採取 {context['funnel_snapshots']} 回")
    m = verdict.metrics
    print(f"モデル検定: λ={m['lambda']} → P(成約0)={m['p0_no_sales']}"
          f" / 実測成約 {m['observed_sales']} 件"
          f" / 露出 {m['exposure_item_months']} 商品・月")
    if m.get("rule_of_three_upper") is not None:
        print(f"実測が許す月次成約確率の上限 (95%): {m['rule_of_three_upper']}")
    if m.get("access_median_weekly") is not None:
        print(f"週あたりアクセス中央値: {m['access_median_weekly']}"
              f" / ほしいもの率: {m.get('wish_rate')}")
    print("\n根拠:")
    for r in verdict.rationale:
        print(f"  - {r}")
    print("\n次の一手:")
    for a in verdict.actions:
        print(f"  → {a}")


def main() -> None:
    parser = argparse.ArgumentParser(description="週次意思決定ゲート")
    parser.add_argument("--sales", type=int, default=None,
                        help="成約数を手動指定 (BUYMA 管理画面の実数が最優先)")
    parser.add_argument("--as-of", help="評価時点 ISO (テスト用、省略時は現在)")
    parser.add_argument("--json", action="store_true", help="JSON 出力")
    args = parser.parse_args()

    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now()
    verdict, context = gather(as_of, args.sales)

    if args.json:
        print(json.dumps(
            {
                "code": verdict.code,
                "headline": verdict.headline,
                "rationale": verdict.rationale,
                "actions": verdict.actions,
                "metrics": verdict.metrics,
                "context": context,
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        print_verdict(verdict, context)


if __name__ == "__main__":
    main()

"""
first_sale_sprint.py
--------------------
「最初の実売データ」を最短で取るスプリントの司令塔。

filter_baseblu_profitable.py の出力 CSV から期待値上位 N 件を選び、
1 商品 = 1 チェックリストの実行手順書 (Markdown) と、進捗を記録する
マニフェスト (data/first_sale_sprint.json) を生成する。

戦略 (docs/strategy/FIRST_SALE_SPRINT.md 参照):
    下書き = ツール (buyma_auto_listing.py --draft、実証済み)
    公開   = 人間 (管理画面で仕上げてクリック。未検証の自動公開は使わない)

使い方 (Mac):
    # 1. スプリント生成 (最新の profitable CSV から上位 10 件)
    python3 scripts/first_sale_sprint.py

    # 2. 手順書に従って 1 件ずつ下書き→公開。公開のたびに記録:
    python3 scripts/first_sale_sprint.py --mark-published 3=133231659

    # 3. 進捗確認
    python3 scripts/first_sale_sprint.py --status

    # サーバー疎通テスト (モックデータ)
    python3 scripts/first_sale_sprint.py --test
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.first_sale import (  # noqa: E402
    SprintCandidate,
    SprintManifest,
    select_sprint_candidates,
)

MANIFEST_PATH = PROJECT_ROOT / "data" / "first_sale_sprint.json"
SPRINT_DIR = PROJECT_ROOT / "outputs" / "sprints"
REPORTS_GLOB = str(PROJECT_ROOT / "outputs" / "reports" / "*_profitable_products.csv")


def find_latest_csv() -> str | None:
    files = sorted(glob.glob(REPORTS_GLOB))
    return files[-1] if files else None


def load_rows(path: str) -> list[dict]:
    # BOM 対策は必ず utf-8-sig (CLAUDE.md 2026-04-19 の知見)
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_manifest() -> SprintManifest | None:
    if not MANIFEST_PATH.exists():
        return None
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return SprintManifest.from_dict(json.load(f))


def save_manifest(manifest: SprintManifest) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, ensure_ascii=False, indent=2)


def render_checklist(manifest: SprintManifest) -> str:
    """1 商品 = 1 ブロックの実行手順書 Markdown を生成する。"""
    lines = [
        "# First Sale Sprint — 実行手順書",
        "",
        f"生成: {manifest.created_at} / 元 CSV: `{os.path.basename(manifest.source_csv)}`",
        "",
        "**ミッション**: 自動化の完成を待たず、下書き=ツール / 公開=人間 の分業で",
        f"{len(manifest.items)} 件を本公開し、実市場の帰還信号 (アクセス/ほしいもの/成約) を開通させる。",
        "",
        "**運用ルール**:",
        "- 公開間隔は 5〜15 分あける (config の LISTING_INTERVAL に合わせる)",
        "- 公開直後に必ず `--mark-published` で記録する (意思決定ゲートの分母になる)",
        "- 2〜3 日おきに `python3 scripts/track_listing_funnel.py` でファネル実測を採取",
        "- 週 1 回 `python3 scripts/decision_gate.py` で次の一手を判定",
        "",
        "---",
        "",
    ]
    for i, it in enumerate(manifest.items, start=1):
        done = "✅ 公開済み" if it.published_at else "⬜ 未公開"
        lines += [
            f"## {i}. {it.title}  ({it.vendor})",
            "",
            f"- 状態: {done}" + (f" (item_id={it.item_id})" if it.item_id else ""),
            f"- 売価 ¥{it.final_price_jpy:,} / 期待利益 ¥{it.expected_profit_jpy:,}"
            f" / 月次成約確率(モデル) {it.sale_probability:.1%}"
            f" / 期待値スコア {it.opportunity_score:,}",
            f"- 仕入元: {it.product_url or '(URL なし)'}",
            "",
            "手順:",
            "",
            f"- [ ] 下書き作成: `python3 scripts/buyma_auto_listing.py --draft "
            f"--from {it.row_index} --limit 1`",
            "- [ ] BUYMA 管理画面で下書きを開き、以下を **人間が** 確認・修正:",
            "  - [ ] 発送地 = 国内 / 神奈川県 (自動設定は 2026-06-16 修正後まだ未検証)",
            f"  - [ ] カテゴリ第 3 階層が適切か ({it.product_type or 'type不明'} — "
            "推定 leaf のカテゴリは categories.json の _todo_harvest 参照)",
            "  - [ ] 画像 (メイン+サブ)・色・サイズ・価格の目視確認",
            "- [ ] 「出品する」を人間がクリック (⚠️ --publish 自動公開は使わない)",
            f"- [ ] 記録: `python3 scripts/first_sale_sprint.py --mark-published "
            f"{it.row_index}=ITEM_ID`",
            "",
        ]
    lines += [
        "---",
        "",
        "全件公開後: `python3 scripts/track_listing_funnel.py` → 2〜3 日おきに実測、",
        "`python3 scripts/decision_gate.py` が次の一手 (継続/露出改善/価格改定/量産) を判定する。",
        "",
    ]
    return "\n".join(lines)


def cmd_generate(args: argparse.Namespace) -> None:
    if args.test:
        rows = _mock_rows()
        source = "(mock)"
        print("🧪 --test: モック 3 件でスプリント生成を疎通確認")
    else:
        source = args.input or find_latest_csv()
        if not source:
            print("❌ profitable CSV が見つかりません。先に filter を実行してください:")
            print("   python3 scripts/filter_baseblu_profitable.py")
            sys.exit(1)
        rows = load_rows(source)
        print(f"📄 入力: {source} ({len(rows)} 行)")

    candidates = select_sprint_candidates(
        rows, limit=args.limit, max_price_jpy=args.max_price
    )
    if not candidates:
        print("❌ action=list の出品候補が 0 件です。filter の結果を確認してください。")
        sys.exit(1)

    existing = load_manifest()
    if existing and existing.published_items() and not args.force:
        print(
            f"⚠️ 既存スプリント ({existing.created_at}) に公開済み "
            f"{len(existing.published_items())} 件の記録があります。"
        )
        print("   上書きすると計測が壊れます。新規生成するなら --force を付けてください。")
        sys.exit(1)

    manifest = SprintManifest(
        created_at=datetime.now().isoformat(timespec="seconds"),
        source_csv=source,
        items=candidates,
    )
    save_manifest(manifest)

    SPRINT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_test" if args.test else ""
    md_path = SPRINT_DIR / f"{datetime.now():%Y-%m-%d}_first_sale_sprint{suffix}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_checklist(manifest))

    lam_month = sum(c.sale_probability for c in candidates)
    print(f"✅ スプリント生成: {len(candidates)} 件")
    print(f"   手順書:       {md_path}")
    print(f"   マニフェスト: {MANIFEST_PATH}")
    print(
        f"   モデル予測: 全件公開なら期待成約 {lam_month:.2f} 件/月 "
        f"(この予測自体を decision_gate.py が検定します)"
    )


def cmd_mark(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    if manifest is None:
        print("❌ マニフェストがありません。先にスプリントを生成してください。")
        sys.exit(1)
    try:
        row_str, item_id = args.mark_published.split("=", 1)
        row_index = int(row_str)
    except ValueError:
        print("❌ 形式: --mark-published ROW=ITEM_ID (例: --mark-published 3=133231659)")
        sys.exit(1)
    when = args.when or datetime.now().isoformat(timespec="seconds")
    if not manifest.mark_published(row_index, item_id.strip(), when):
        rows = ", ".join(str(it.row_index) for it in manifest.items)
        print(f"❌ row_index={row_index} が見つかりません (候補: {rows})")
        sys.exit(1)
    save_manifest(manifest)
    n_pub = len(manifest.published_items())
    print(f"✅ 記録: row {row_index} → item_id={item_id} ({when})")
    print(f"   公開済み {n_pub}/{len(manifest.items)} 件")


def cmd_status(_args: argparse.Namespace) -> None:
    manifest = load_manifest()
    if manifest is None:
        print("(スプリント未生成)")
        return
    n_pub = len(manifest.published_items())
    print(f"📋 スプリント {manifest.created_at} — 公開 {n_pub}/{len(manifest.items)} 件")
    for it in manifest.items:
        mark = "✅" if it.published_at else "⬜"
        extra = f" item={it.item_id} 公開={it.published_at}" if it.published_at else ""
        print(
            f"  {mark} row {it.row_index}: {it.title[:40]} "
            f"¥{it.final_price_jpy:,} p={it.sale_probability:.1%}{extra}"
        )
    print("\n次: python3 scripts/decision_gate.py で判定を確認")


def _mock_rows() -> list[dict]:
    return [
        {
            "title": f"Mock Item {i}",
            "vendor": "MOCKBRAND",
            "action": "list",
            "final_price_jpy": str(100000 + i * 10000),
            "expected_profit_jpy": str(20000 + i * 1000),
            "sale_probability": "0.08",
            "opportunity_score": str(1600 + i * 100),
            "product_url": f"https://example.com/products/mock-{i}",
            "product_type": "BAGS",
        }
        for i in range(1, 4)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="First Sale Sprint 司令塔")
    parser.add_argument("--input", help="profitable CSV (省略時は最新を自動選択)")
    parser.add_argument("--limit", type=int, default=10, help="出品件数 (default 10)")
    parser.add_argument("--max-price", type=int, default=None,
                        help="売価上限 (円)。初スプリントは低単価から始めるのも手")
    parser.add_argument("--mark-published", metavar="ROW=ITEM_ID",
                        help="公開を記録 (例: 3=133231659)")
    parser.add_argument("--when", help="公開日時 ISO (省略時は現在時刻)")
    parser.add_argument("--status", action="store_true", help="進捗表示")
    parser.add_argument("--force", action="store_true",
                        help="公開済み記録があっても新規スプリントで上書き")
    parser.add_argument("--test", action="store_true", help="モックデータで疎通確認")
    args = parser.parse_args()

    if args.mark_published:
        cmd_mark(args)
    elif args.status:
        cmd_status(args)
    else:
        cmd_generate(args)


if __name__ == "__main__":
    main()

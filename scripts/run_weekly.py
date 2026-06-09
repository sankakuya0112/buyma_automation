"""
run_weekly.py — 週次パイプラインを 1 コマンドで実行するラッパー (Mac 用)
--------------------------------------------------------------------------
従来は 4-5 個のスクリプトを正しい順番・正しい引数で手入力する必要があり、
タイプミスや順番間違いの原因になっていた。本スクリプトは全工程を自動で
正しい順序で実行する。

使い方 (Mac のターミナルで):

    cd ~/buyma_automation
    python3 scripts/run_weekly.py

これだけ。実行される工程:

    1. baseblu セール商品の取得 (baseblu_sales_to_csv.py)
    2. 利益フィルタ 1 回目 (filter_baseblu_profitable.py、相場なし)
    3. BUYMA 相場の取得 (fetch_buyma_market_prices.py --csv latest)
    4. 利益フィルタ 2 回目 (相場連動で final_price / 期待値スコア確定)
    5. 需要インデックス更新 + 需要×供給の交点表示 (scout_demand.py)

オプション:
    --skip-scrape    今日すでに取得済みのセール CSV を再利用
    --skip-market    相場取得を飛ばす (フィルタ 1 回のみ)
    --market-limit N 相場取得の件数上限 (時間短縮、デバッグ用)
    --probe          ブランド単位の需要調査も行う (時間がかかる)
    --dry-run        実行せずコマンドだけ表示

途中で失敗した場合は、失敗した工程のコマンドとエラーが表示されるので、
その出力を Claude にそのまま貼り付ければ診断できる。
"""

from __future__ import annotations

import argparse
import glob
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
REPORTS = PROJECT_ROOT / "outputs" / "reports"


def _latest(pattern: str) -> str | None:
    files = sorted(glob.glob(str(REPORTS / pattern)))
    return files[-1] if files else None


def _today_file(pattern: str) -> str | None:
    """今日の日付のファイルがあれば返す。"""
    today = datetime.now().strftime("%Y-%m-%d")
    path = REPORTS / pattern.replace("*", today, 1)
    return str(path) if path.exists() else None


def build_steps(args) -> list[dict]:
    """実行する工程のリストを組み立てる (テスト可能な純粋関数)。

    各 step: {"name": 表示名, "cmd": list[str], "required": 失敗時に中断するか}
    cmd が None の step は実行時に動的に解決する (market JSON のパス等)。
    """
    py = sys.executable or "python3"
    steps: list[dict] = []

    if not args.skip_scrape:
        steps.append({
            "name": "① baseblu セール商品の取得",
            "cmd": [py, str(SCRIPTS / "baseblu_sales_to_csv.py")],
            "required": True,
        })

    steps.append({
        "name": "② 利益フィルタ (1回目・相場なし)",
        "cmd": [py, str(SCRIPTS / "filter_baseblu_profitable.py")],
        "required": True,
    })

    if not args.skip_market:
        market_cmd = [py, str(SCRIPTS / "fetch_buyma_market_prices.py"), "--csv", "latest"]
        if args.market_limit:
            market_cmd += ["--limit", str(args.market_limit)]
        steps.append({
            "name": "③ BUYMA 相場の取得 (時間がかかります)",
            "cmd": market_cmd,
            "required": True,
        })
        steps.append({
            "name": "④ 利益フィルタ (2回目・相場連動)",
            "cmd": None,            # market JSON のパスを実行時に解決
            "resolver": "filter_with_market",
            "required": True,
        })

    if args.probe:
        steps.append({
            "name": "⑤ ブランド需要の能動調査 (--probe)",
            "cmd": [py, str(SCRIPTS / "scout_demand.py"), "--probe-from-csv", "latest"],
            "required": False,
        })

    steps.append({
        "name": "⑥ 需要インデックス更新 + 需要×供給の交点",
        "cmd": [py, str(SCRIPTS / "scout_demand.py"), "--match-source", "latest"],
        "required": False,
    })

    return steps


def resolve_dynamic_cmd(step: dict) -> list[str] | None:
    """実行時にしか決まらないコマンドを解決する。"""
    py = sys.executable or "python3"
    if step.get("resolver") == "filter_with_market":
        market_json = _latest("*_market_prices.json")
        if not market_json:
            print("   ⚠️ 相場 JSON が見つからないためスキップします")
            return None
        return [py, str(SCRIPTS / "filter_baseblu_profitable.py"), "--market", market_json]
    return None


def main():
    parser = argparse.ArgumentParser(description="週次パイプラインの一括実行")
    parser.add_argument("--skip-scrape", action="store_true",
                        help="セール CSV の再取得を飛ばす")
    parser.add_argument("--skip-market", action="store_true",
                        help="相場取得を飛ばす")
    parser.add_argument("--market-limit", type=int,
                        help="相場取得の件数上限")
    parser.add_argument("--probe", action="store_true",
                        help="ブランド単位の需要調査も実行 (時間がかかる)")
    parser.add_argument("--dry-run", action="store_true",
                        help="実行せずコマンドだけ表示")
    args = parser.parse_args()

    steps = build_steps(args)

    print("=" * 60)
    print(f"🚀 週次パイプライン ({datetime.now():%Y-%m-%d %H:%M})")
    print("=" * 60)
    print("実行予定:")
    for s in steps:
        print(f"   {s['name']}")
    print()

    failed = []
    for step in steps:
        if step["cmd"] is None and args.dry_run:
            # 動的工程は実行時にパスが決まるため、dry-run では説明だけ表示
            print("─" * 60)
            print(f"▶ {step['name']}")
            print("   $ (実行時に最新の market JSON を自動指定して filter を再実行)")
            continue

        cmd = step["cmd"] or resolve_dynamic_cmd(step)
        if cmd is None and step["cmd"] is None:
            continue

        print("─" * 60)
        print(f"▶ {step['name']}")
        print(f"   $ {' '.join(cmd)}")
        if args.dry_run:
            continue

        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        if result.returncode != 0:
            failed.append(step["name"])
            print()
            print(f"❌ 失敗: {step['name']} (exit code {result.returncode})")
            print("   ↑ この上に表示されているエラーを Claude に貼り付けてください。")
            if step["required"]:
                print("   必須工程のため、ここで中断します。")
                sys.exit(1)
            print("   任意工程のため、続行します。")

    if args.dry_run:
        print("\n(dry-run のため何も実行していません)")
        return

    print()
    print("=" * 60)
    if failed:
        print(f"⚠️ 完了 (失敗した任意工程: {', '.join(failed)})")
    else:
        print("✅ 全工程完了！")
    final_csv = _latest("*_baseblu_profitable_products.csv")
    if final_csv:
        print(f"📄 出品候補 CSV (期待値順): {final_csv}")
    print()
    print("次のステップ (出品テスト):")
    print("   python3 scripts/buyma_auto_listing.py --draft --limit 1 --hold")


if __name__ == "__main__":
    main()

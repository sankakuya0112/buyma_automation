"""為替キャッシュ (data/fx_rates.json) を ECB 参考レートで更新する。

    python3 scripts/update_fx_rates.py          # 取得して保存
    python3 scripts/update_fx_rates.py --show   # 通信せず現在の設定を表示

原価計算は「キャッシュ (または EUR_TO_JPY 等の手動指定) × (1 + FX_BUFFER_PCT)」を使う。
詳細は app/core/fx.py。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import fx  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    from app.utils.env import load_project_env
    load_project_env()   # .env の為替・手数料・ガード設定を計算前に反映 (シェルの値が優先)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--show", action="store_true", help="通信せずに現在の設定を表示")
    args = ap.parse_args(argv)
    if not args.show:
        res = fx.refresh_rates()
        if res.get("ok"):
            print(f"✅ ECB 参考レート ({res['date']}) を保存: EUR={res['EUR']} USD={res['USD']} GBP={res['GBP']}")
        else:
            print(f"⚠️ 取得失敗: {res.get('error')} → 既存キャッシュ / 固定値で続行します")
    for cur in ("EUR", "USD", "GBP"):
        print("   " + fx.describe(cur))
    return 0


if __name__ == "__main__":
    sys.exit(main())

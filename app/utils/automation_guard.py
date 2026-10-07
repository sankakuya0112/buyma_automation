"""BUYMA のブラウザ自動操作 (Playwright) の利用制限。

BUYMA は「許諾していない外部プログラムの使用」「自動出品ツール」を禁止しており、
検知されるとアカウント停止になり得る (https://qa.buyma.com/information/news/30118.html)。
2026-10-07 の方針で、BUYMA への出品・更新は公式の手段に切り替える:

  - 一括出品 CSV (items.csv + colorsizes.csv の zip、下書きで登録) … scripts/generate_bulk_upload.py
  - BUYMA Personal Shopper API (申請中/予定) … https://specification.personal-shopper-api.buyma.com/

そのため buyma.com をブラウザで自動操作するスクリプトは既定で停止する。
過去の下書き保存の検証などでどうしても使う場合だけ、本人が内容を理解した上で
環境変数 BUYMA_ALLOW_BROWSER_AUTOMATION=1 を設定する (公開・停止・価格更新は対象外で、
これらはこの設定でも動かない)。
"""

from __future__ import annotations

import os
import sys

ENV_NAME = "BUYMA_ALLOW_BROWSER_AUTOMATION"

POLICY_MESSAGE = (
    "BUYMA のブラウザ自動操作は停止中です (BUYMA の規約で許諾のない外部プログラムは禁止)。\n"
    "   出品は公式の一括出品 CSV を使ってください:\n"
    "     python3 scripts/generate_bulk_upload.py --limit 3   → outputs/bulk/*.zip を BUYMA の\n"
    "     「一括出品編集」(https://www.buyma.com/my/sell/bulk/) から本人がアップロード (下書き)\n"
    "   公開は BUYMA の画面で本人が内容を確認してから押してください。"
)


def browser_automation_allowed() -> bool:
    return os.getenv(ENV_NAME, "").strip() == "1"


def require_browser_automation(feature: str) -> None:
    """許可されていなければメッセージを出して終了 (exit code 2)。"""
    if browser_automation_allowed():
        print(f"⚠️ {ENV_NAME}=1 のため「{feature}」を実行します。BUYMA の規約上のリスクを理解した上で使ってください。",
              file=sys.stderr)
        return
    print(f"⛔ 「{feature}」は実行しません。\n   {POLICY_MESSAGE}\n"
          f"   (検証目的でどうしても使う場合のみ {ENV_NAME}=1)", file=sys.stderr)
    sys.exit(2)


def refuse_buyma_write(feature: str) -> None:
    """公開・停止・価格更新など BUYMA 上の状態を変える自動操作は常に拒否する。"""
    print(f"⛔ 「{feature}」は自動では行いません (ブラウザ自動操作による公開・停止・価格更新は廃止)。\n"
          "   BUYMA の画面で本人が操作するか、一括出品 CSV / 公式 API (承認制) を使ってください。",
          file=sys.stderr)
    sys.exit(2)

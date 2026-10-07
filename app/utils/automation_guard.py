"""BUYMA のブラウザ自動操作 (Playwright) の利用制限。

BUYMA は「許諾していない外部プログラムの使用」「自動出品ツール」を禁止しており、
検知されるとアカウント停止になり得る (https://qa.buyma.com/information/news/30118.html)。
2026-10-07 の方針で、BUYMA への出品・更新は本人の手作業か公式の手段に切り替える:

  - 既定: 出品シート (scripts/generate_listing_sheet.py) を見ながら、本人が通常の出品フォーム
    (https://www.buyma.com/my/sell/new?tab=b) に入力して下書き保存
  - 自動化の予定: BUYMA Personal Shopper API (2026-05-14 全出品者に公開・申込制、本人が申込中)
    … https://specification.personal-shopper-api.buyma.com/
  - 一括出品 CSV (scripts/generate_bulk_upload.py) は権限のあるアカウント (ショップ等) 向け。
    一般の個人アカウントでは一括出品編集ページ (/my/sell/bulk/) が「アクセスが許可されていません」になる
    (2026-10-08 本人のアカウントで確認)

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
    "   出品は出品シートを見ながら本人が通常の出品フォームに入力してください:\n"
    "     python3 scripts/generate_listing_sheet.py --limit 3   → outputs/listing_sheets/<日時>/ を開き、\n"
    "     https://www.buyma.com/my/sell/new?tab=b に入力して「下書き保存」\n"
    "   自動化は公式 API (申込制) の承認後に対応予定。一括出品 CSV は権限のあるアカウントのみ。\n"
    "   公開は BUYMA の画面で本人が内容を確認してから押してください。"
)


def browser_automation_allowed() -> bool:
    return os.getenv(ENV_NAME, "").strip() == "1"


_warned: set[str] = set()


def require_browser_automation(feature: str) -> None:
    """許可されていなければメッセージを出して終了 (exit code 2)。

    CLI の入口だけでなく、BUYMA をブラウザで操作する関数 (ログイン・入力・相場取得) の先頭でも呼ぶ
    (別スクリプトから関数を直接 import して呼ばれても止まるように)。許可時の警告は機能ごとに 1 回。
    """
    if browser_automation_allowed():
        if feature not in _warned:
            _warned.add(feature)
            print(f"⚠️ {ENV_NAME}=1 のため「{feature}」を実行します。BUYMA の規約上のリスクを理解した上で使ってください。",
                  file=sys.stderr)
        return
    print(f"⛔ 「{feature}」は実行しません。\n   {POLICY_MESSAGE}\n"
          f"   (検証目的でどうしても使う場合のみ {ENV_NAME}=1)", file=sys.stderr)
    sys.exit(2)


def refuse_buyma_write(feature: str) -> None:
    """公開・停止・価格更新など BUYMA 上の状態を変える自動操作は常に拒否する。"""
    print(f"⛔ 「{feature}」は自動では行いません (ブラウザ自動操作による公開・停止・価格更新は廃止)。\n"
          "   BUYMA の画面で本人が操作するか、承認後の公式 API を使ってください。",
          file=sys.stderr)
    sys.exit(2)

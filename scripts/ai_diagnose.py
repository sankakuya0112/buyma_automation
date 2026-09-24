"""
ai_diagnose.py — Mac 実走のエラーログを AI に診断させる (チャットに貼る代わり)
--------------------------------------------------------------------------
    python3 scripts/buyma_auto_listing.py --draft --limit 1 2>&1 | tee /tmp/run.log
    python3 scripts/ai_diagnose.py --log /tmp/run.log --context "下書き保存で 422"
    cat /tmp/run.log | python3 scripts/ai_diagnose.py      # 標準入力でも可

ログ末尾 6,000 文字だけを、メールアドレス・パスワード・API キーをマスクして送ります。
Sonnet 5 (standard 階層) を使い、1 回あたり数円〜十数円です。
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

from app.ai.client import get_ai_client  # noqa: E402
from app.ai.tasks.diagnose import diagnose_failure, prepare_log  # noqa: E402


def format_diagnosis(d: dict) -> str:
    lines = [
        f"🩺 要約: {d.get('summary', '')}",
        f"🔍 推定原因 ({d.get('confidence', '?')}): {d.get('probable_cause', '')}",
        "🛠 対処手順:",
    ]
    for i, step in enumerate(d.get("fix_steps") or [], 1):
        lines.append(f"   {i}. {step}")
    if d.get("needs_code_change"):
        lines.append("💻 コード修正が必要です → クラウド側の Claude に以下のファイルと合わせて依頼してください:")
        for f in d.get("files_to_check") or []:
            lines.append(f"   - {f}")
    elif d.get("files_to_check"):
        lines.append("📄 確認するファイル: " + ", ".join(d["files_to_check"]))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="実走ログの AI 診断")
    parser.add_argument("--log", help="ログファイル (省略時は標準入力)")
    parser.add_argument("--context", default="", help="状況の一言 (例: 下書き保存で 422)")
    parser.add_argument("--show-redacted", action="store_true", help="送信内容 (マスク後) を表示")
    args = parser.parse_args(argv)

    text = Path(args.log).read_text(encoding="utf-8", errors="replace") if args.log else sys.stdin.read()
    if not text.strip():
        print("❌ ログが空です")
        return 1
    if args.show_redacted:
        print("----- 送信内容 (マスク後) -----")
        print(prepare_log(text))
        print("-------------------------------")

    client = get_ai_client()
    if not client.available:
        print(f"ℹ️ AI はオフ ({client.why_unavailable()})。ログ末尾をクラウド側の Claude に貼って診断を依頼してください。")
        return 2
    result = diagnose_failure(text, client, context=args.context)
    if not result:
        print("⚠️ 診断結果を取得できませんでした。ログ末尾を Claude に貼ってください。")
        return 2
    print(format_diagnosis(result))
    s = client.session_summary()
    print(f"\n(AI 費用 今回 ≈¥{s['cost_jpy']:,.1f} / 今週累計 ¥{s['weekly_spent_jpy']:,.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

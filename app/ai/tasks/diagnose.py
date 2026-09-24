"""障害診断 (standard 階層 / Sonnet 5)。

Mac 実走で出たエラーログを「チャットに貼って人が読む」代わりに、
ログ末尾だけを秘密情報マスク付きで渡し、原因と対処手順を構造化で受け取る。
CLAUDE.md に蓄積した BUYMA フォームの罠を system に固定し (キャッシュ対象)、
同じ失敗の再診断コストを下げる。
"""

from __future__ import annotations

import re
from typing import Optional

MAX_LOG_CHARS = 6000

KNOWN_PITFALLS = """## 既知の罠 (CLAUDE.md より要約)
- BUYMA 出品フォームは画面外要素を DOM に置かない (lazy render)。_scroll_through_page でホイールスクロール後に探す。
- 品番/識別メモ欄はブランド選択後にしか DOM に出ない。select_brand → set_sku の順序固定。
- react-select / サジェスト候補 / radio は JS の click() や onChange 直叩きでは state が更新されない。Playwright の locator.click() か native setter + input/change dispatch が必要。
- ブランド API は https://cdn-suggest.buyma.com/brand_suggest?keyword=。未登録ブランドは brands.json の unregistered に入れて filter で除外。
- 画像アップロードは page.expect_response(POST item_image.json) で待つ。page.on だと二重アップロードになる。
- 商品コメントのアクセント文字 (è 等) は validation で弾かれる → _strip_accents。
- タブ panel id (#react-tabs-N) は固定でない → aria-controls から取る。
- 第 2 階層カテゴリが実在名でないと保存 API が 422 (cate_id)。categories.json の _tier2_valid を参照。
- 発送地の都道府県 select は「国内」radio 後に遅延描画。全域 select 走査は禁止 (ページ状態を壊す)。
- 下書き保存ボタンは Playwright click 必須。JS click は React が反応しない。
- サーバー (Claude Code クラウド) からは baseblu.com / buyma.com に接続できない。実走は Mac。
"""

SYSTEM_PROMPT = (
    "あなたは BUYMA 自動出品ツール (Python + Playwright) の保守エンジニアです。"
    "Mac で実行したスクリプトのログ末尾を読み、原因と対処を **プログラミング初心者にも実行できる手順** で示してください。\n"
    "推測は推測と明記し、確信度を confidence に入れること。コード修正が必要ならどのファイルの何を直すかを files_to_check に列挙。\n"
    "対処手順 (fix_steps) は「ターミナルで打つコマンド」または「管理画面での操作」の単位で、順番に。\n\n"
    + KNOWN_PITFALLS
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "probable_cause": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "fix_steps": {"type": "array", "items": {"type": "string"}},
        "needs_code_change": {"type": "boolean"},
        "files_to_check": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "probable_cause", "confidence", "fix_steps", "needs_code_change", "files_to_check"],
    "additionalProperties": False,
}

_SECRET_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "<api-key>"),
    (re.compile(r"(?i)(password|passwd|pwd|token|secret|api[_-]?key)(\s*[:=]\s*)(\S+)"), r"\1\2<redacted>"),
    (re.compile(r"\b[0-9a-f]{32,}\b"), "<hex>"),
]


def redact_secrets(text: str) -> str:
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


def prepare_log(log_text: str) -> str:
    """末尾 MAX_LOG_CHARS だけ残し、秘密情報をマスクする。"""
    text = (log_text or "").strip()
    if len(text) > MAX_LOG_CHARS:
        text = "…(前略)…\n" + text[-MAX_LOG_CHARS:]
    return redact_secrets(text)


def diagnose_failure(log_text: str, client, context: str = "") -> Optional[dict]:
    """ログ → {summary, probable_cause, confidence, fix_steps[], needs_code_change, files_to_check[]}。"""
    body = prepare_log(log_text)
    if not body:
        return None
    user = ""
    if context:
        user += f"状況: {context.strip()[:500]}\n\n"
    user += "ログ末尾:\n```\n" + body + "\n```"
    data = client.complete_json("diagnose", SYSTEM_PROMPT, user, OUTPUT_SCHEMA)
    if not isinstance(data, dict):
        return None
    data.setdefault("fix_steps", [])
    data.setdefault("files_to_check", [])
    return data

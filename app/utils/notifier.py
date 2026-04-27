"""エラー通知モジュール (Phase 2-4)。

Slack Webhook / SMTP メール経由で通知を送る。日次バッチ実行時の失敗検知や
重要イベント (本公開成功 / 大量 SKIP 発生など) の通知に使う。

設定 (環境変数 / .env):
    SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=user@example.com
    SMTP_PASSWORD=app_password
    NOTIFY_EMAIL_FROM=user@example.com
    NOTIFY_EMAIL_TO=admin@example.com
    NOTIFY_DRY_RUN=1   # 実送信せず stdout に出力 (テスト用)

設定がなければ silent skip するため、開発環境で誤通知の心配なし。

使い方:
    from app.utils.notifier import notify, notify_error

    notify("info", "出品成功", "GIVENCHY ドレス 1 件出品完了")

    try:
        ...
    except Exception as e:
        notify_error("baseblu_scraper", e, context={"page": 3})
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import traceback
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)

# requests は遅延 import (テストで mock しやすい + import 失敗 graceful)


_LEVEL_EMOJI = {
    "info": "ℹ️",
    "success": "✅",
    "warn": "⚠️",
    "warning": "⚠️",
    "error": "❌",
    "critical": "🚨",
}


def _is_dry_run() -> bool:
    return os.environ.get("NOTIFY_DRY_RUN", "").strip() not in ("", "0", "false", "False")


def send_slack(text: str, webhook_url: Optional[str] = None, timeout: int = 10) -> bool:
    """Slack Incoming Webhook にプレーンテキストを送る。

    Returns:
        送信成功なら True、未設定 / 失敗で False
    """
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return False

    if _is_dry_run():
        print(f"[NOTIFY DRY_RUN slack] {text}")
        return True

    try:
        import requests
        resp = requests.post(
            url,
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            logger.warning("Slack notify failed: %d %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:
        logger.warning("Slack notify exception: %s", e)
        return False


def send_email(
    subject: str,
    body: str,
    to: Optional[str] = None,
    from_addr: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> bool:
    """SMTP で平文メールを送る。設定不足や送信失敗で False。"""
    to_addr = to or os.environ.get("NOTIFY_EMAIL_TO", "").strip()
    sender = from_addr or os.environ.get("NOTIFY_EMAIL_FROM", "").strip()
    host = smtp_host or os.environ.get("SMTP_HOST", "").strip()
    port = smtp_port or int(os.environ.get("SMTP_PORT", "587") or 587)
    user = smtp_user or os.environ.get("SMTP_USER", "").strip()
    password = smtp_password or os.environ.get("SMTP_PASSWORD", "").strip()

    if not (to_addr and sender and host):
        return False

    if _is_dry_run():
        print(f"[NOTIFY DRY_RUN email] to={to_addr} subject={subject!r}")
        print(body)
        return True

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception as e:
        logger.warning("Email notify exception: %s", e)
        return False


def notify(level: str, title: str, body: str = "") -> dict:
    """Slack + email の両方に通知を送る。

    Returns:
        {"slack": bool, "email": bool} — 各チャネルの送信結果
    """
    emoji = _LEVEL_EMOJI.get(level.lower(), "")
    slack_text = f"{emoji} *{title}*"
    if body:
        slack_text += f"\n```\n{body}\n```"

    email_subject = f"[buyma_automation:{level}] {title}"
    email_body = f"{title}\n\n{body}" if body else title

    return {
        "slack": send_slack(slack_text),
        "email": send_email(email_subject, email_body),
    }


def notify_error(
    operation: str,
    exc: BaseException,
    context: Optional[dict] = None,
) -> dict:
    """例外発生時のエラー通知を送る。"""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    body_lines = [f"Operation: {operation}", f"Exception: {type(exc).__name__}: {exc}"]
    if context:
        body_lines.append(f"Context: {json.dumps(context, ensure_ascii=False, default=str)}")
    body_lines.append("")
    body_lines.append(tb)
    return notify("error", f"{operation} 失敗", "\n".join(body_lines))

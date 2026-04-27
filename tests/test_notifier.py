"""app.utils.notifier のユニットテスト (Phase 2-4)。"""

from __future__ import annotations

import os
import sys
import unittest
import unittest.mock as mock
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils import notifier


def _clear_notify_env():
    """notifier 関連の環境変数を一旦クリアするヘルパー。"""
    keys = [
        "SLACK_WEBHOOK_URL", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
        "NOTIFY_EMAIL_TO", "NOTIFY_EMAIL_FROM", "NOTIFY_DRY_RUN",
    ]
    return {k: "" for k in keys}


class TestSendSlack(unittest.TestCase):
    def test_no_webhook_returns_false(self):
        with mock.patch.dict(os.environ, _clear_notify_env(), clear=False):
            result = notifier.send_slack("hello")
        self.assertFalse(result)

    def test_dry_run_skips_request(self):
        env = _clear_notify_env()
        env["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/X"
        env["NOTIFY_DRY_RUN"] = "1"
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("requests.post") as m:
                result = notifier.send_slack("hello")
        self.assertTrue(result)
        m.assert_not_called()

    def test_success_calls_webhook(self):
        env = _clear_notify_env()
        env["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/X"
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("requests.post") as m:
                m.return_value = mock.MagicMock(status_code=200, text="ok")
                result = notifier.send_slack("hello")
        self.assertTrue(result)
        m.assert_called_once()
        call_kwargs = m.call_args.kwargs
        self.assertIn("data", call_kwargs)
        self.assertIn("hello", call_kwargs["data"].decode("utf-8"))

    def test_http_error_returns_false(self):
        env = _clear_notify_env()
        env["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/X"
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("requests.post") as m:
                m.return_value = mock.MagicMock(status_code=500, text="err")
                result = notifier.send_slack("hello")
        self.assertFalse(result)

    def test_exception_returns_false(self):
        env = _clear_notify_env()
        env["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/X"
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("requests.post", side_effect=Exception("boom")):
                result = notifier.send_slack("hello")
        self.assertFalse(result)

    def test_explicit_url_overrides_env(self):
        with mock.patch.dict(os.environ, _clear_notify_env(), clear=False):
            with mock.patch("requests.post") as m:
                m.return_value = mock.MagicMock(status_code=200, text="ok")
                result = notifier.send_slack("hello", webhook_url="https://override")
        self.assertTrue(result)
        self.assertEqual(m.call_args.args[0], "https://override")


class TestSendEmail(unittest.TestCase):
    def test_missing_config_returns_false(self):
        with mock.patch.dict(os.environ, _clear_notify_env(), clear=False):
            result = notifier.send_email("subj", "body")
        self.assertFalse(result)

    def test_dry_run_skips_smtp(self):
        env = _clear_notify_env()
        env.update({
            "SMTP_HOST": "smtp.example.com",
            "NOTIFY_EMAIL_FROM": "from@x",
            "NOTIFY_EMAIL_TO": "to@x",
            "NOTIFY_DRY_RUN": "1",
        })
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("smtplib.SMTP") as m:
                result = notifier.send_email("subj", "body")
        self.assertTrue(result)
        m.assert_not_called()

    def test_success_calls_smtp(self):
        env = _clear_notify_env()
        env.update({
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USER": "u",
            "SMTP_PASSWORD": "p",
            "NOTIFY_EMAIL_FROM": "from@x",
            "NOTIFY_EMAIL_TO": "to@x",
        })
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("smtplib.SMTP") as m:
                instance = m.return_value.__enter__.return_value
                result = notifier.send_email("subj", "body")
        self.assertTrue(result)
        instance.starttls.assert_called_once()
        instance.login.assert_called_once_with("u", "p")
        instance.send_message.assert_called_once()

    def test_smtp_exception_returns_false(self):
        env = _clear_notify_env()
        env.update({
            "SMTP_HOST": "smtp.example.com",
            "NOTIFY_EMAIL_FROM": "from@x",
            "NOTIFY_EMAIL_TO": "to@x",
        })
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("smtplib.SMTP", side_effect=Exception("boom")):
                result = notifier.send_email("subj", "body")
        self.assertFalse(result)


class TestNotify(unittest.TestCase):
    def test_returns_both_channel_results(self):
        with mock.patch.dict(os.environ, _clear_notify_env(), clear=False):
            result = notifier.notify("info", "title", "body")
        # 何も設定なし → 両方 False
        self.assertEqual(result, {"slack": False, "email": False})

    def test_emoji_inserted_in_slack_message(self):
        env = _clear_notify_env()
        env["SLACK_WEBHOOK_URL"] = "https://x"
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("requests.post") as m:
                m.return_value = mock.MagicMock(status_code=200, text="ok")
                notifier.notify("error", "fail", "details")
        sent = m.call_args.kwargs["data"].decode("utf-8")
        # json.dumps の default ensure_ascii=True で emoji は ❌ にエスケープされる
        self.assertIn("\\u274c", sent)
        self.assertIn("fail", sent)


class TestNotifyError(unittest.TestCase):
    def test_includes_exception_and_context(self):
        env = _clear_notify_env()
        env["SLACK_WEBHOOK_URL"] = "https://x"
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("requests.post") as m:
                m.return_value = mock.MagicMock(status_code=200, text="ok")
                try:
                    raise ValueError("boom")
                except ValueError as e:
                    notifier.notify_error("scrape", e, context={"page": 3})
        sent = m.call_args.kwargs["data"].decode("utf-8")
        self.assertIn("scrape", sent)
        self.assertIn("ValueError", sent)
        self.assertIn("boom", sent)
        self.assertIn("page", sent)


class TestIsDryRun(unittest.TestCase):
    def test_default_false(self):
        with mock.patch.dict(os.environ, _clear_notify_env(), clear=False):
            self.assertFalse(notifier._is_dry_run())

    def test_explicit_truthy(self):
        for val in ["1", "true", "True", "yes"]:
            with mock.patch.dict(os.environ, {"NOTIFY_DRY_RUN": val}, clear=False):
                self.assertTrue(notifier._is_dry_run(), f"failed for {val!r}")

    def test_falsy_values(self):
        for val in ["0", "false", "False", ""]:
            with mock.patch.dict(os.environ, {"NOTIFY_DRY_RUN": val}, clear=False):
                self.assertFalse(notifier._is_dry_run(), f"failed for {val!r}")


if __name__ == "__main__":
    unittest.main()

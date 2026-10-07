"""BUYMA のブラウザ自動操作を既定で止める方針 (2026-10-07) と、出品結果 CSV の修正のテスト。"""

from __future__ import annotations

import contextlib
import csv
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from app.utils import automation_guard as guard  # noqa: E402
from app.utils.listing_helpers import (  # noqa: E402
    RESULT_FIELDNAMES,
    append_result_rows,
    build_result_row,
    listing_sizes,
    normalize_item_id,
)

SCRIPTS = PROJECT_ROOT / "scripts"
BUYMA_BROWSER_SCRIPTS = (
    "buyma_auto_listing.py", "fetch_buyma_market_prices.py", "track_listing_funnel.py",
    "harvest_buyma_categories.py", "scout_demand.py",
)


class GuardTest(unittest.TestCase):
    def test_blocked_by_default(self):
        with patch.dict(os.environ, {guard.ENV_NAME: ""}), contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                guard.require_browser_automation("x")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("generate_bulk_upload.py", err.getvalue())

    def test_allowed_only_with_exact_1(self):
        for val, allowed in (("1", True), ("true", False), ("0", False), ("yes", False)):
            with patch.dict(os.environ, {guard.ENV_NAME: val}):
                self.assertEqual(guard.browser_automation_allowed(), allowed, val)
        with patch.dict(os.environ, {guard.ENV_NAME: "1"}), contextlib.redirect_stderr(io.StringIO()):
            guard.require_browser_automation("x")   # 例外にならない

    def test_write_always_refused_even_when_allowed(self):
        with patch.dict(os.environ, {guard.ENV_NAME: "1"}), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                guard.refuse_buyma_write("publish")
        self.assertEqual(cm.exception.code, 2)


class AutoListingPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import buyma_auto_listing
        cls.bal = buyma_auto_listing

    def _policy(self, args, env="1"):
        with patch.dict(os.environ, {guard.ENV_NAME: env}), contextlib.redirect_stderr(io.StringIO()):
            self.bal.check_cli_policy(args)

    def test_publish_refused_even_when_allowed(self):
        with self.assertRaises(SystemExit):
            self._policy(["--publish"])

    def test_yes_removed(self):
        with self.assertRaises(SystemExit):
            self._policy(["--draft", "--yes"])

    def test_draft_needs_opt_in(self):
        with self.assertRaises(SystemExit):
            self._policy(["--draft"], env="")
        self._policy(["--draft"], env="1")

    def test_publish_code_removed(self):
        text = (SCRIPTS / "buyma_auto_listing.py").read_text(encoding="utf-8")
        self.assertNotIn("def publish_product", text)
        self.assertNotIn('("published", "published")', text)
        self.assertNotIn("skip_confirm", text)


class NoAntiDetectionTest(unittest.TestCase):
    def test_buyma_scripts_have_no_ua_spoof_or_automation_flag(self):
        for name in BUYMA_BROWSER_SCRIPTS:
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
            self.assertNotIn("--disable-blink-features=AutomationControlled\"", code, name)
            self.assertNotIn("user_agent=", code, name)
            self.assertIn("require_browser_automation", text, name)


class ResultRowTest(unittest.TestCase):
    def test_item_id_numeric_only(self):
        self.assertEqual(normalize_item_id("published"), "")
        self.assertEqual(normalize_item_id(" 133231149 "), "133231149")
        self.assertEqual(normalize_item_id(None), "")
        row = build_result_row({"title": "t"}, "published", "published", "now")
        self.assertEqual(row["item_id"], "")

    def test_listing_sizes(self):
        self.assertEqual(listing_sizes({"available_sizes": "38, 40", "sizes": "36, 38, 40, 42"}), "38, 40")
        # 空文字 = 出せるサイズが無い (売切れ)。全サイズには落とさない
        self.assertEqual(listing_sizes({"available_sizes": "", "sizes": "S, M"}), "")
        # 列が無い旧形式 (None) だけ全サイズ。ただし高いサイズがある商品は落とさない
        self.assertEqual(listing_sizes({"sizes": "S, M"}), "S, M")
        self.assertEqual(listing_sizes({"available_sizes": None, "priced_out_sizes": "L", "sizes": "S, L"}), "")
        row = build_result_row({"available_sizes": "38"}, "draft", "1", "now")
        self.assertEqual(row["listed_sizes"], "38")

    def test_append_keeps_previous_rows_and_upgrades_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "2026-10-07_auto_listing_results.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["status", "item_id", "title", "vendor", "price", "processed_at"])
                w.writeheader()
                w.writerow({"status": "draft", "item_id": "100", "title": "old", "vendor": "X",
                            "price": "1", "processed_at": "t"})
            n = append_result_rows(path, [build_result_row({"title": "new"}, "draft", "200", "t2")])
            self.assertEqual(n, 2)
            n = append_result_rows(path, [build_result_row({"title": "new2"}, "draft", "300", "t3")])
            self.assertEqual(n, 3)
            with open(path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(tuple(reader.fieldnames), RESULT_FIELDNAMES)
        self.assertEqual([r["item_id"] for r in rows], ["100", "200", "300"])


class OperationBoundaryGuardTest(unittest.TestCase):
    """CLI を通さず関数を直接呼んでも BUYMA のブラウザ操作が始まらないこと。"""

    def _blocked(self, fn, *args):
        with patch.dict(os.environ, {guard.ENV_NAME: ""}), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                fn(*args)
        self.assertEqual(cm.exception.code, 2)

    def test_market_fetch_function(self):
        import fetch_buyma_market_prices as m
        self._blocked(m.fetch_market_for, "GUCCI", "bag", object())

    def test_listing_functions(self):
        import buyma_auto_listing as bal
        self._blocked(bal.login, object(), "e", "p")
        self._blocked(bal.save_draft, object())
        self._blocked(bal.process_product, object(), {}, True, {}, {})

    def test_funnel_run(self):
        import track_listing_funnel as t
        self._blocked(t.run, 1, False, True)


class EnvLoaderTest(unittest.TestCase):
    def test_env_file_fills_only_unset_keys(self):
        from app.utils.env import load_project_env
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# c\nFX_BUFFER_PCT=\"0.05\" # 5%\nexport BUYMA_TRANSFER_FEE_JPY='220'\nEUR_TO_JPY=1 # x\n",
                            encoding="utf-8")
            with patch.dict(os.environ, {"EUR_TO_JPY": "180"}, clear=False):
                os.environ.pop("FX_BUFFER_PCT", None)
                os.environ.pop("BUYMA_TRANSFER_FEE_JPY", None)
                loaded = load_project_env(path)
                self.assertEqual(os.environ["FX_BUFFER_PCT"], "0.05")
                self.assertEqual(os.environ["BUYMA_TRANSFER_FEE_JPY"], "220")
                self.assertEqual(os.environ["EUR_TO_JPY"], "180")   # シェルの値が優先
                for k in loaded:
                    os.environ.pop(k, None)
        self.assertEqual(sorted(loaded), ["BUYMA_TRANSFER_FEE_JPY", "FX_BUFFER_PCT"])

    def test_fallback_parser_handles_quotes_and_comments(self):
        from app.utils.env import _parse_line
        self.assertEqual(_parse_line('EUR_TO_JPY="250" # comment'), ("EUR_TO_JPY", "250"))
        self.assertEqual(_parse_line("export A='x y'"), ("A", "x y"))
        self.assertEqual(_parse_line("B=3 # c"), ("B", "3"))
        self.assertIsNone(_parse_line("# only comment"))


class OtherScriptGuardsTest(unittest.TestCase):
    def test_market_fetch_blocked_but_no_fetch_allowed(self):
        import fetch_buyma_market_prices as m
        with patch.dict(os.environ, {guard.ENV_NAME: ""}), \
                patch.object(sys, "argv", ["x", "--brand", "GUCCI", "--keyword", "bag"]), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                m.main()
        self.assertEqual(cm.exception.code, 2)

    def test_funnel_blocked(self):
        import track_listing_funnel as t
        with patch.dict(os.environ, {guard.ENV_NAME: ""}), patch.object(sys, "argv", ["x"]), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                t.main()
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

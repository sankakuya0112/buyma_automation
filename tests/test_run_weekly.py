"""run_weekly.py の工程組み立て (BUYMA のブラウザ自動操作は opt-in の時だけ) のテスト。"""

from __future__ import annotations

import sys
import unittest
from argparse import Namespace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import run_weekly as rw  # noqa: E402


def _args(**kw) -> Namespace:
    base = dict(skip_scrape=False, skip_market=False, market_limit=None, probe=True, dry_run=False,
                allow_browser=False)
    base.update(kw)
    return Namespace(**base)


class BuildStepsTest(unittest.TestCase):
    def test_market_and_probe_skipped_without_opt_in(self):
        names = [s["name"] for s in rw.build_steps(_args())]
        self.assertFalse(any(n.startswith("③") or n.startswith("④") or n.startswith("⑤") for n in names))
        self.assertTrue(any(n.startswith("②") for n in names))
        self.assertTrue(any(n.startswith("⑥") for n in names))

    def test_market_with_opt_in(self):
        names = [s["name"] for s in rw.build_steps(_args(allow_browser=True))]
        self.assertTrue(any(n.startswith("③") for n in names))
        self.assertTrue(any(n.startswith("⑤") for n in names))

    def test_latest_report_is_importable(self):
        self.assertTrue(callable(rw.latest_report))


if __name__ == "__main__":
    unittest.main()

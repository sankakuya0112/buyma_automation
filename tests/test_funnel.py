"""app.core.funnel (出品リスト解析 + スナップショット差分) のユニットテスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.funnel import (
    count_sold,
    diff_snapshots,
    extract_seller_items,
    latest_metrics_by_item,
    parse_count,
    weekly_access_rates,
)

# 出品リスト行の想定 DOM (初回 Mac 実走の --debug-html で規約を検証する)
SAMPLE_HTML = """
<div class="sell-item">
  <a href="/item/123456789"><img src="x.jpg"></a>
  <a href="/my/sell/123456789/edit?tab=b">【GUCCI】GG Marmont Shoulder Bag</a>
  <span>出品中</span>
  <dl><dt>アクセス数</dt><dd>1,234</dd></dl>
  <dl><dt>ほしいもの登録数</dt><dd>56</dd></dl>
</div>
<div class="sell-item">
  <a href="/my/sell/987654321/edit">【PRADA】Re-Edition Bag</a>
  <span>売り切れ</span>
  <dl><dt>アクセス数</dt><dd>89</dd></dl>
  <dl><dt>ほしいもの登録数</dt><dd>0</dd></dl>
  <dl><dt>カートに入れた人数</dt><dd>2</dd></dl>
</div>
"""


class TestParseCount(unittest.TestCase):
    def test_comma_separated(self):
        self.assertEqual(parse_count("1,234"), 1234)

    def test_none_and_garbage(self):
        self.assertEqual(parse_count(None), 0)
        self.assertEqual(parse_count("abc"), 0)


class TestExtractSellerItems(unittest.TestCase):
    def test_extracts_two_items_with_counts(self):
        items = extract_seller_items(SAMPLE_HTML)
        self.assertEqual(len(items), 2)

        first = items[0]
        self.assertEqual(first["item_id"], "123456789")
        self.assertIn("GG Marmont", first["title"])
        self.assertEqual(first["status"], "出品中")
        self.assertEqual(first["access"], 1234)
        self.assertEqual(first["wish"], 56)

        second = items[1]
        self.assertEqual(second["item_id"], "987654321")
        self.assertEqual(second["status"], "売り切れ")
        self.assertEqual(second["access"], 89)
        self.assertEqual(second["cart"], 2)

    def test_duplicate_links_are_merged(self):
        # 画像リンクとタイトルリンクで同一 item_id が 2 回出ても 1 件に
        items = extract_seller_items(SAMPLE_HTML)
        ids = [it["item_id"] for it in items]
        self.assertEqual(len(ids), len(set(ids)))

    def test_empty_html(self):
        self.assertEqual(extract_seller_items(""), [])
        self.assertEqual(extract_seller_items("<html>no items</html>"), [])


class TestSnapshotDiff(unittest.TestCase):
    def _snap(self, access, wish, status="出品中"):
        return {
            "ts": "2026-07-03T00:00:00",
            "items": [
                {"item_id": "1", "title": "t", "status": status,
                 "access": access, "wish": wish, "cart": 0}
            ],
        }

    def test_first_snapshot_uses_absolute_values(self):
        diff = diff_snapshots(None, self._snap(10, 2))
        self.assertEqual(diff["totals"]["d_access"], 10)
        self.assertEqual(diff["totals"]["d_wish"], 2)

    def test_delta_against_previous(self):
        diff = diff_snapshots(self._snap(10, 2), self._snap(15, 2))
        self.assertEqual(diff["totals"]["d_access"], 5)
        self.assertEqual(diff["totals"]["d_wish"], 0)

    def test_new_sold_detected_on_status_change(self):
        diff = diff_snapshots(self._snap(10, 2), self._snap(11, 2, status="売り切れ"))
        self.assertEqual(diff["totals"]["new_sold"], 1)
        self.assertEqual(count_sold(self._snap(11, 2, status="取引中")["items"]), 1)


class TestHistoryHelpers(unittest.TestCase):
    def _history(self):
        return {
            "snapshots": [
                {"ts": "2026-07-01T00:00:00",
                 "items": [{"item_id": "1", "access": 7, "wish": 0, "status": "出品中"}]},
                {"ts": "2026-07-03T00:00:00",
                 "items": [{"item_id": "1", "access": 14, "wish": 1, "status": "出品中"}]},
            ]
        }

    def test_latest_metrics_wins(self):
        latest = latest_metrics_by_item(self._history())
        self.assertEqual(latest["1"]["access"], 14)

    def test_weekly_access_rate(self):
        # 公開 7 日で累計 14 アクセス → 14/7×7 = 14/週
        rates = weekly_access_rates(self._history(), ["1"], {"1": 7.0})
        self.assertEqual(len(rates), 1)
        self.assertAlmostEqual(rates[0], 14.0, places=6)

    def test_weekly_access_min_one_day(self):
        # 公開当日 (0 日) は 1 日として扱い過大評価を防ぐ
        rates = weekly_access_rates(self._history(), ["1"], {"1": 0.0})
        self.assertAlmostEqual(rates[0], 14.0 * 7.0, places=6)

    def test_unknown_item_skipped(self):
        rates = weekly_access_rates(self._history(), ["999"], {"999": 7.0})
        self.assertEqual(rates, [])


if __name__ == "__main__":
    unittest.main()

"""app.core.first_sale (スプリント選定 + モデル予測 λ) のユニットテスト。"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.first_sale import (
    SprintCandidate,
    SprintManifest,
    days_until_decisive,
    elapsed_days,
    expected_sales_lambda,
    exposure_months,
    select_sprint_candidates,
)


def _row(title, action="list", price="100000", profit="20000",
         p="0.10", opp="2000"):
    return {
        "title": title,
        "vendor": "BRAND",
        "action": action,
        "final_price_jpy": price,
        "expected_profit_jpy": profit,
        "sale_probability": p,
        "opportunity_score": opp,
        "product_url": "https://example.com/p",
        "product_type": "BAGS",
    }


class TestSelectSprintCandidates(unittest.TestCase):
    def test_skip_and_review_rows_are_excluded(self):
        rows = [_row("a"), _row("b", action="skip"), _row("c", action="review")]
        picked = select_sprint_candidates(rows, limit=10)
        self.assertEqual([c.title for c in picked], ["a"])

    def test_row_index_is_file_position_not_sorted_position(self):
        # --from N は CSV のファイル順を参照するため、選定後も元の行番号を保持する
        rows = [
            _row("low", opp="100"),
            _row("skipme", action="skip"),
            _row("high", opp="9999"),
        ]
        picked = select_sprint_candidates(rows, limit=2)
        self.assertEqual(picked[0].title, "high")
        self.assertEqual(picked[0].row_index, 3)  # ファイル内 3 行目
        self.assertEqual(picked[1].title, "low")
        self.assertEqual(picked[1].row_index, 1)

    def test_sorted_by_opportunity_then_profit(self):
        rows = [
            _row("b", opp="500", profit="10000"),
            _row("a", opp="500", profit="30000"),
            _row("c", opp="900", profit="1000"),
        ]
        picked = select_sprint_candidates(rows, limit=3)
        self.assertEqual([c.title for c in picked], ["c", "a", "b"])

    def test_max_price_and_zero_price_filters(self):
        rows = [
            _row("cheap", price="50000"),
            _row("expensive", price="500000"),
            _row("broken", price="0"),
        ]
        picked = select_sprint_candidates(rows, limit=10, max_price_jpy=100000)
        self.assertEqual([c.title for c in picked], ["cheap"])

    def test_limit(self):
        rows = [_row(f"t{i}") for i in range(20)]
        self.assertEqual(len(select_sprint_candidates(rows, limit=7)), 7)


class TestLambdaMath(unittest.TestCase):
    def _published(self, p, days_ago, as_of):
        return SprintCandidate(
            row_index=1, title="t", vendor="v", final_price_jpy=1,
            expected_profit_jpy=1, sale_probability=p, opportunity_score=1,
            item_id="1", published_at=(as_of - timedelta(days=days_ago)).isoformat(),
        )

    def test_lambda_is_probability_times_elapsed_months(self):
        as_of = datetime(2026, 7, 3, 12, 0, 0)
        items = [self._published(0.10, 30, as_of)]  # 0.10 × 30/30 = 0.10
        self.assertAlmostEqual(expected_sales_lambda(items, as_of), 0.10, places=6)

    def test_unpublished_items_do_not_contribute(self):
        as_of = datetime(2026, 7, 3)
        item = SprintCandidate(
            row_index=1, title="t", vendor="v", final_price_jpy=1,
            expected_profit_jpy=1, sale_probability=0.5, opportunity_score=1,
        )
        self.assertEqual(expected_sales_lambda([item], as_of), 0.0)

    def test_elapsed_days_capped_at_listing_lifetime(self):
        as_of = datetime(2026, 7, 3)
        published_at = (as_of - timedelta(days=365)).isoformat()
        self.assertEqual(elapsed_days(published_at, as_of), 90.0)

    def test_exposure_months(self):
        as_of = datetime(2026, 7, 3)
        items = [self._published(0.1, 15, as_of), self._published(0.1, 45, as_of)]
        self.assertAlmostEqual(exposure_months(items, as_of), 2.0, places=6)

    def test_days_until_decisive_decreases_with_more_listings(self):
        as_of = datetime(2026, 7, 3)
        few = [self._published(0.10, 0, as_of) for _ in range(5)]
        many = [self._published(0.10, 0, as_of) for _ in range(20)]
        d_few = days_until_decisive(few, as_of)
        d_many = days_until_decisive(many, as_of)
        self.assertIsNotNone(d_few)
        self.assertIsNotNone(d_many)
        self.assertLess(d_many, d_few)

    def test_days_until_decisive_none_when_nothing_published(self):
        as_of = datetime(2026, 7, 3)
        item = SprintCandidate(
            row_index=1, title="t", vendor="v", final_price_jpy=1,
            expected_profit_jpy=1, sale_probability=0.5, opportunity_score=1,
        )
        self.assertIsNone(days_until_decisive([item], as_of))


class TestManifest(unittest.TestCase):
    def _manifest(self):
        return SprintManifest(
            created_at="2026-07-03T00:00:00",
            source_csv="x.csv",
            items=[
                SprintCandidate(
                    row_index=3, title="t", vendor="v", final_price_jpy=100,
                    expected_profit_jpy=10, sale_probability=0.1,
                    opportunity_score=1,
                )
            ],
        )

    def test_mark_published_and_roundtrip(self):
        m = self._manifest()
        ok = m.mark_published(3, "133231659", "2026-07-04T10:00:00")
        self.assertTrue(ok)
        restored = SprintManifest.from_dict(m.to_dict())
        self.assertEqual(restored.items[0].item_id, "133231659")
        self.assertEqual(len(restored.published_items()), 1)

    def test_mark_published_unknown_row(self):
        m = self._manifest()
        self.assertFalse(m.mark_published(99, "1", "2026-07-04T10:00:00"))
        self.assertEqual(len(m.published_items()), 0)


if __name__ == "__main__":
    unittest.main()

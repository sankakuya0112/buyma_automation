"""filter の BUYMA 未登録ブランド除外 (Phase 2d) のユニットテスト。

2026-06-10 実走で、出品候補 16 件中 5 件が AFTERCOAT (brands.json の
unregistered リスト掲載 = 出品時に必ず brand_not_found でスキップ) であり、
出品枠を浪費していた。filter 段階で除外する。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from filter_baseblu_profitable import (  # noqa: E402
    is_brand_unregistered,
    load_unregistered_brands,
)


class LoadUnregisteredBrandsTest(unittest.TestCase):
    def _write_brands(self, data) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        json.dump(data, f, ensure_ascii=False)
        f.close()
        return f.name

    def test_loads_uppercased_set(self):
        path = self._write_brands({
            "brands": {"gucci": {"brand_id": 203}},
            "unregistered": ["AFTERCOAT", "The Latest"],
        })
        try:
            out = load_unregistered_brands(path)
            self.assertEqual(out, {"AFTERCOAT", "THE LATEST"})
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_unregistered_brands("/nonexistent/brands.json"), set())

    def test_missing_key_returns_empty(self):
        path = self._write_brands({"brands": {}})
        try:
            self.assertEqual(load_unregistered_brands(path), set())
        finally:
            os.unlink(path)

    def test_broken_json_returns_empty(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        f.write("{broken")
        f.close()
        try:
            self.assertEqual(load_unregistered_brands(f.name), set())
        finally:
            os.unlink(f.name)

    def test_real_brands_json_loads(self):
        """リポジトリ同梱の data/brands.json が読める (AFTERCOAT 掲載確認)。"""
        out = load_unregistered_brands()
        self.assertIn("AFTERCOAT", out)


class IsBrandUnregisteredTest(unittest.TestCase):
    UNREG = {"AFTERCOAT", "THE LATEST"}

    def test_exact_match(self):
        self.assertTrue(is_brand_unregistered("AFTERCOAT", self.UNREG))

    def test_case_insensitive(self):
        self.assertTrue(is_brand_unregistered("Aftercoat", self.UNREG))
        self.assertTrue(is_brand_unregistered("the latest", self.UNREG))

    def test_whitespace_tolerant(self):
        self.assertTrue(is_brand_unregistered("  AFTERCOAT  ", self.UNREG))

    def test_registered_brand_passes(self):
        self.assertFalse(is_brand_unregistered("GUCCI", self.UNREG))

    def test_empty_inputs(self):
        self.assertFalse(is_brand_unregistered("", self.UNREG))
        self.assertFalse(is_brand_unregistered("AFTERCOAT", set()))


if __name__ == "__main__":
    unittest.main()

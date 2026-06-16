"""data/categories.json のスキーマ検証 (Phase 2d / 2026-06-16)。

2026-06-10 の実走で「第2階層が BUYMA に実在しない名前」だと保存 API が
422 (cate_id: 第2カテゴリを選択してください) で弾くことが判明した。
出品フォームから実採取した第2階層名 (_tier2_valid) と全マッピングを
照合し、無効な第2階層を CI で検出する。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATEGORIES_PATH = PROJECT_ROOT / "data" / "categories.json"


class CategoriesSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CATEGORIES_PATH, encoding="utf-8") as f:
            cls.data = json.load(f)
        cls.valid_t2 = set(cls.data.get("_tier2_valid", []))

    def _iter_paths(self):
        yield "default", self.data["default"]
        for m in self.data["mappings"]:
            yield f"{m['product_type']}.default", m["default"]
            for kw in m["keywords"]:
                yield f"{m['product_type']}/{','.join(kw['match'])}", kw["path"]

    def test_tier2_valid_list_present(self):
        self.assertTrue(self.valid_t2, "_tier2_valid が空 (採取データが必要)")

    def test_all_paths_have_three_levels(self):
        for ctx, path in self._iter_paths():
            self.assertEqual(len(path), 3, f"{ctx}: 階層数が3でない {path}")

    def test_all_tier1_is_ladies(self):
        for ctx, path in self._iter_paths():
            self.assertEqual(path[0], "レディースファッション", f"{ctx}: tier1 不正")

    def test_all_tier2_are_valid(self):
        """全マッピングの第2階層が実在名であること (422 防止の核心)。"""
        bad = []
        for ctx, path in self._iter_paths():
            if path[1] not in self.valid_t2:
                bad.append(f"{ctx}: tier2='{path[1]}'")
        self.assertEqual(bad, [], "実在しない第2階層: " + "; ".join(bad))

    def test_known_pants_mapping_fixed(self):
        """回帰: pants が ボトムス 配下になっていること (旧 'パンツ>パンツ' バグ)。"""
        clothing = next(m for m in self.data["mappings"] if m["product_type"] == "CLOTHING")
        pants = next(kw for kw in clothing["keywords"] if "pants" in kw["match"])
        self.assertEqual(pants["path"][1], "ボトムス")
        self.assertEqual(pants["path"][2], "パンツ")

    def test_no_legacy_invalid_tier2_names(self):
        """旧バグの無効 tier2 名が残っていないこと。"""
        legacy_invalid = {"小物", "パンツ", "スカート", "デニム", "ワンピース", "シューズ"}
        used_t2 = {path[1] for _, path in self._iter_paths()}
        leaked = used_t2 & legacy_invalid
        self.assertEqual(leaked, set(), f"無効な旧 tier2 名が残存: {leaked}")


if __name__ == "__main__":
    unittest.main()

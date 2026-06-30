from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from legal_redactor.admin_division import AdminDivisionDetector
from legal_redactor.china_admin_rules import (
    decompose_admin_path,
    detect_china_admin_rule_candidates,
    normalize_province_name,
)
from legal_redactor.config import PipelineConfig
from legal_redactor.pipeline import RedactionPipeline


class ChinaAdminRulesTests(unittest.TestCase):
    def test_normalize_province_name(self) -> None:
        self.assertEqual(normalize_province_name("广东省"), "广东省")
        self.assertEqual(normalize_province_name("广东"), "广东省")
        self.assertEqual(normalize_province_name("内蒙古自治区"), "内蒙古自治区")
        self.assertIsNone(normalize_province_name("星河省"))

    def test_decompose_admin_path_three_levels(self) -> None:
        parts = decompose_admin_path("广东省深圳市南山区")
        self.assertEqual(parts["prov"], "广东省")
        self.assertEqual(parts["city"], "深圳市")
        self.assertEqual(parts["county"], "南山区")

    def test_detect_china_admin_rule_candidates_for_municipality_path(self) -> None:
        text = "北京市海淀区中关村大街发生争议。"
        candidates = detect_china_admin_rule_candidates(text)
        texts = {candidate.text for candidate in candidates}
        self.assertTrue("北京市" in texts or "北京市海淀区" in texts)
        self.assertTrue(any("海淀" in value for value in texts))

    def test_detect_city_after_address_marker(self) -> None:
        text = "被告：李四，住宁波市。"
        candidates = detect_china_admin_rule_candidates(text)
        texts = {candidate.text for candidate in candidates}
        self.assertIn("宁波市", texts)
        self.assertNotIn("住宁波市", texts)

    def test_decompose_compact_hebei_path(self) -> None:
        parts = decompose_admin_path("河北唐山迁安市")
        self.assertEqual(parts["prov"], "河北省")
        self.assertEqual(parts["city"], "唐山")
        self.assertEqual(parts["county"], "迁安市")

    def test_nationwide_pipeline_masks_guangdong_shenzhen_nanshan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "china.sqlite"
            _write_sample_china_db(db_path)
            config = replace(
                PipelineConfig.offline_without_llm(),
                enable_hebei_admin_db=False,
                enable_china_admin_db=True,
                china_admin_db_path=str(db_path),
                enable_china_admin_rules=True,
            )
            pipeline = RedactionPipeline(config=config)
            with mock.patch("legal_redactor.pipeline.load_all_samples", return_value=({}, set())):
                with mock.patch("legal_redactor.pipeline.load_trusted_sample_mappings", return_value=[]):
                    result = pipeline.redact("广东省深圳市南山区某项目发生争议。")

        self.assertNotIn("广东省", result.redacted_text)
        self.assertNotIn("深圳市", result.redacted_text)
        self.assertNotIn("南山区", result.redacted_text)
        originals = {entry.original for entry in result.redaction_map.mappings}
        self.assertTrue({"广东省", "深圳市", "南山区", "广东省深圳市南山区"} & originals)


def _write_sample_china_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE admin_divisions (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                level TEXT NOT NULL,
                parent_code TEXT,
                parent_name TEXT,
                city_name TEXT,
                county_name TEXT,
                township_name TEXT,
                village_name TEXT,
                entity_type TEXT NOT NULL,
                urban_rural_code TEXT,
                source TEXT,
                source_year TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute("CREATE TABLE admin_aliases (alias TEXT, canonical_name TEXT, division_code TEXT, alias_type TEXT, source TEXT, confidence REAL)")
        rows = [
            ("44", "广东省", "广东省", "province", "", "", "", "", "", "", "location", "", "test", "2026", 1),
            ("4403", "深圳市", "广东省深圳市", "city", "44", "广东省", "深圳市", "", "", "", "location", "", "test", "2026", 1),
            ("440305", "南山区", "广东省深圳市南山区", "county", "4403", "深圳市", "深圳市", "南山区", "", "", "location", "", "test", "2026", 1),
        ]
        conn.executemany(
            "INSERT INTO admin_divisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


class ChinaAdminDetectorTests(unittest.TestCase):
    def test_detector_reads_province_city_county(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "china.sqlite"
            _write_sample_china_db(db_path)
            detector = AdminDivisionDetector(
                db_path,
                source="china_admin_db",
                region_label="全国三级行政区划",
                max_level="county_city",
            )
            candidates = detector.detect("住所地广东省深圳市南山区。")
            texts = {candidate.text for candidate in candidates}
            self.assertIn("广东省", texts)
            self.assertIn("深圳市", texts)
            self.assertIn("南山区", texts)


if __name__ == "__main__":
    unittest.main()
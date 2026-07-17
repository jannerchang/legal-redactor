from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

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
        self.assertIn("北京市", texts)
        self.assertIn("海淀区", texts)
        self.assertNotIn("北京市海淀区", texts)
        self.assertEqual(decompose_admin_path("北京市海淀区"), {"prov": "北京市", "county": "海淀区"})

    def test_detect_china_admin_rule_trims_leading_context_before_municipality(self) -> None:
        text = "原告后搬至北京市海淀区。"
        candidates = detect_china_admin_rule_candidates(text)
        texts = {candidate.text for candidate in candidates}
        self.assertIn("北京市", texts)
        self.assertIn("海淀区", texts)
        self.assertNotIn("北京市海淀区", texts)
        self.assertNotIn("后搬至北京市海淀区", texts)

    def test_detect_city_after_address_marker(self) -> None:
        text = "被告：李四，住宁波市。"
        candidates = detect_china_admin_rule_candidates(text)
        texts = {candidate.text for candidate in candidates}
        self.assertIn("宁波市", texts)
        self.assertNotIn("住宁波市", texts)

    def test_rule_candidates_reject_prose_before_known_city(self) -> None:
        text = "其后由石家庄市供水公司施工。"
        candidates = detect_china_admin_rule_candidates(text)

        assert all(candidate.text != "其后由石家庄市" for candidate in candidates)

        result = RedactionPipeline(config=PipelineConfig.offline_without_llm()).redact(text)
        assert "其后由石家庄市" not in {entry.original for entry in result.redaction_map.mappings}

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
            result = pipeline.redact("广东省深圳市南山区某项目发生争议。")

        self.assertNotIn("广东省", result.redacted_text)
        self.assertNotIn("深圳市", result.redacted_text)
        self.assertNotIn("南山区", result.redacted_text)
        originals = {entry.original for entry in result.redaction_map.mappings}
        self.assertEqual({"广东省", "深圳市", "南山区"}, originals & {"广东省", "深圳市", "南山区", "广东省深圳市", "广东省深圳市南山区"})
        self.assertNotIn("广东省深圳市", originals)
        self.assertNotIn("广东省深圳市南山区", originals)

    def test_nationwide_pipeline_masks_municipality_without_china_db(self) -> None:
        config = replace(
            PipelineConfig.offline_without_llm(),
            enable_hebei_admin_db=False,
            enable_china_admin_db=True,
            china_admin_db_path="/tmp/legal-redactor-missing-china-admin.sqlite",
            enable_china_admin_rules=True,
        )
        pipeline = RedactionPipeline(config=config)
        text = "原告张三住广东省深圳市南山区科技园，后搬至北京市海淀区。"
        result = pipeline.redact(text)

        self.assertNotIn("广东省", result.redacted_text)
        self.assertNotIn("深圳市", result.redacted_text)
        self.assertNotIn("南山区", result.redacted_text)
        self.assertNotIn("北京市", result.redacted_text)
        self.assertNotIn("海淀区", result.redacted_text)
        originals = {entry.original for entry in result.redaction_map.mappings}
        self.assertTrue({"广东省", "深圳市", "南山区", "北京市", "海淀区"}.issubset(originals))
        self.assertNotIn("广东省深圳市南山区", originals)
        self.assertNotIn("北京市海淀区", originals)

    def test_pipeline_keeps_admin_components_not_overlapping_paths(self) -> None:
        pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
        text = "北京市通州区、河北省石家庄市藁城区均有项目。"

        result = pipeline.redact(text)
        originals = {entry.original for entry in result.redaction_map.mappings}

        assert {"北京市", "通州区", "河北省", "石家庄市", "藁城区"} <= originals
        assert "北京市通州区" not in originals
        assert "河北省石家庄市" not in originals
        assert "河北省石家庄市藁城区" not in originals


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

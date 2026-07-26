from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from legal_redactor.admin_division import AdminDivisionDetector
from legal_redactor.entity_registry import (
    FullDocumentEntityRegistry,
    RegistryEntity,
    RegistryValidationResult,
)
from legal_redactor.llm import FullDocumentRegistryExtraction
from legal_redactor.config import PipelineConfig
from legal_redactor.pipeline import RedactionPipeline


class ChinaAdminRulesTests(unittest.TestCase):
    def test_suffix_grammar_is_not_a_runtime_discovery_source(self) -> None:
        from unittest.mock import patch

        text = "临时用水水源提供至施工场区，按照同期贷款市调整价格。"
        extraction = FullDocumentRegistryExtraction(
            validation=RegistryValidationResult(registry=FullDocumentEntityRegistry())
        )
        config = replace(
            PipelineConfig.max_effect(),
            enable_hebei_admin_db=False,
            enable_china_admin_db=False,
        )

        with patch(
            "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
            return_value=extraction,
        ):
            result = RedactionPipeline(config=config).redact(text)

        self.assertEqual([], [entry for entry in result.redaction_map.mappings if entry.type == "location"])

    def test_sqlite_admin_remains_authoritative_when_llm_omits_location(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "china.sqlite"
            _write_sample_china_db(db_path)
            config = replace(
                PipelineConfig.max_effect(),
                enable_hebei_admin_db=False,
                enable_china_admin_db=True,
                china_admin_db_path=str(db_path),
            )
            extraction = FullDocumentRegistryExtraction(
                validation=RegistryValidationResult(
                    registry=FullDocumentEntityRegistry(
                        entities=(RegistryEntity("person-1", "person", "张三", ("张三",)),)
                    )
                )
            )
            with patch(
                "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
                return_value=extraction,
            ):
                result = RedactionPipeline(config=config).redact("原告张三住广东省深圳市南山区。")

        originals = {entry.original for entry in result.redaction_map.mappings}
        self.assertTrue({"张三", "广东省", "深圳市"}.issubset(originals))
        self.assertNotIn("南山区", originals)

    def test_llm_location_still_passes_registry_suffix_gate(self) -> None:
        from unittest.mock import patch

        extraction = FullDocumentRegistryExtraction(
            validation=RegistryValidationResult(
                registry=FullDocumentEntityRegistry(
                    entities=(RegistryEntity("location-1", "location", "重新确认", ("重新确认",)),)
                )
            )
        )
        config = replace(
            PipelineConfig.max_effect(),
            enable_hebei_admin_db=False,
            enable_china_admin_db=False,
        )
        with patch(
            "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
            return_value=extraction,
        ):
            result = RedactionPipeline(config=config).redact("双方重新确认合同内容。")

        self.assertNotIn("重新确认", {entry.original for entry in result.redaction_map.mappings})
    def test_llm_location_supplement_is_limited_to_province_and_city(self) -> None:
        from unittest.mock import patch

        extraction = FullDocumentRegistryExtraction(
            validation=RegistryValidationResult(
                registry=FullDocumentEntityRegistry(
                    entities=(
                        RegistryEntity(
                            "location-1",
                            "location",
                            "广东省",
                            ("广东省", "深圳市", "南山区"),
                        ),
                    )
                )
            )
        )
        config = replace(
            PipelineConfig.max_effect(),
            enable_hebei_admin_db=False,
            enable_china_admin_db=False,
        )
        with patch(
            "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
            return_value=extraction,
        ):
            result = RedactionPipeline(config=config).redact(
                "住所地广东省深圳市南山区。"
            )

        originals = {entry.original for entry in result.redaction_map.mappings}
        self.assertTrue({"广东省", "深圳市"}.issubset(originals))
        self.assertNotIn("南山区", originals)


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
    def test_detector_reads_only_province_and_city_for_nationwide_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "china.sqlite"
            _write_sample_china_db(db_path)
            detector = AdminDivisionDetector(
                db_path,
                source="china_admin_db",
                region_label="全国省市行政区划",
                max_level="city",
            )
            candidates = detector.detect("住所地广东省深圳市南山区。")
            texts = {candidate.text for candidate in candidates}
            self.assertIn("广东省", texts)
            self.assertIn("深圳市", texts)
            self.assertNotIn("南山区", texts)

    def test_hebei_pipeline_redacts_through_county_and_street(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "hebei.sqlite"
            _write_sample_hebei_db(db_path)
            config = replace(
                PipelineConfig.max_effect(),
                enable_hebei_admin_db=True,
                hebei_admin_db_path=str(db_path),
                enable_china_admin_db=False,
            )
            extraction = FullDocumentRegistryExtraction(
                validation=RegistryValidationResult(registry=FullDocumentEntityRegistry())
            )
            with patch(
                "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
                return_value=extraction,
            ):
                result = RedactionPipeline(config=config).redact(
                    "住所地河北省石家庄市长安区跃进街道。"
                )

        originals = {entry.original for entry in result.redaction_map.mappings}
        self.assertTrue(
            {"河北省", "石家庄市", "长安区", "跃进街道"}.issubset(originals)
        )


def _write_sample_hebei_db(path: Path) -> None:
    _write_sample_china_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM admin_divisions")
        rows = [
            ("13", "河北省", "河北省", "province", "", "", "", "", "", "", "location", "", "test", "2026", 1),
            ("1301", "石家庄市", "河北省石家庄市", "city", "13", "河北省", "石家庄市", "", "", "", "location", "", "test", "2026", 1),
            ("130102", "长安区", "河北省石家庄市长安区", "county", "1301", "石家庄市", "石家庄市", "长安区", "", "", "location", "", "test", "2026", 1),
            ("130102001", "跃进街道", "河北省石家庄市长安区跃进街道", "township", "130102", "长安区", "石家庄市", "长安区", "跃进街道", "", "location", "", "test", "2026", 1),
        ]
        conn.executemany(
            "INSERT INTO admin_divisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


if __name__ == "__main__":
    unittest.main()

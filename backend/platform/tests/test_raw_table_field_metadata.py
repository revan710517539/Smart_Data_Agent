from __future__ import annotations

import unittest

from backend.platform.api.routes.assets import (
    _normalized_raw_fields,
    _raw_table_with_metadata_overlay,
)
from backend.platform.assets.store import _validate_asset_schema


class RawTableFieldMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source_fields = [
            {"fieldNameEn": "report_date", "fieldNameCn": "日期", "type": "date", "isTime": True},
            {"fieldNameEn": "branch", "fieldNameCn": "机构", "type": "string"},
            {"fieldNameEn": "count", "fieldNameCn": "件数", "type": "integer", "isMetric": True},
            {"fieldNameEn": "amount", "fieldNameCn": "金额", "type": "decimal", "isMetric": True},
            {"fieldNameEn": "approval_rate", "fieldNameCn": "通过率", "type": "decimal", "isMetric": True},
        ]

    def test_default_contract_infers_role_rate_date_and_one_dimension_key(self) -> None:
        fields = _normalized_raw_fields(self.source_fields)
        by_code = {field["fieldNameEn"]: field for field in fields}
        self.assertEqual(by_code["report_date"]["semanticRole"], "date")
        self.assertEqual(by_code["report_date"]["dateFormat"], "yyyy-MM-dd")
        self.assertEqual(by_code["approval_rate"]["type"], "rate")
        self.assertEqual(by_code["amount"]["type"], "decimal")
        self.assertEqual(by_code["count"]["type"], "integer")
        self.assertEqual([field["fieldNameEn"] for field in fields if field["isPrimaryKey"]], ["branch"])

    def test_overlay_allows_composite_dimension_key_and_explicit_metric_type(self) -> None:
        configured = _normalized_raw_fields(self.source_fields)
        for field in configured:
            if field["fieldNameEn"] in {"report_date", "branch"}:
                field.update({"semanticRole": "dimension", "type": "string", "isPrimaryKey": True})
            if field["fieldNameEn"] == "approval_rate":
                field["type"] = "decimal"
        fields = _normalized_raw_fields(self.source_fields, configured)
        self.assertEqual(
            [field["fieldNameEn"] for field in fields if field["isPrimaryKey"]],
            ["report_date", "branch"],
        )
        self.assertEqual(next(field for field in fields if field["fieldNameEn"] == "approval_rate")["type"], "decimal")

    def test_overlay_fails_closed_when_source_fields_change(self) -> None:
        with self.assertRaisesRegex(ValueError, "raw_table_metadata_fields_changed"):
            _normalized_raw_fields(self.source_fields, [{"fieldNameEn": "unknown", "semanticRole": "dimension", "type": "string"}])

    def test_stale_schema_overlay_is_not_applied(self) -> None:
        table = {
            "sourceKey": "source-1", "schemaFingerprint": "schema-new", "primaryKey": "",
            "fields": self.source_fields,
        }
        overlay = {
            "id": "overlay-1", "metadataOverlayVersion": 1, "sourceKey": "source-1",
            "schemaFingerprint": "schema-old", "fields": [], "lockVersion": 3,
        }
        result = _raw_table_with_metadata_overlay(table, overlay)
        self.assertTrue(result["metadataConfigSchemaChanged"])
        self.assertEqual(result["metadataConfigId"], "")
        self.assertEqual(result["primaryKeys"], ["branch"])

    def test_store_rejects_primary_key_that_is_not_dimension(self) -> None:
        invalid = {
            "id": "raw-metadata", "metadataOverlayVersion": 1, "sourceKey": "source-1",
            "schemaFingerprint": "schema-1", "tableNameEn": "raw_table", "tableNameCn": "原始表",
            "source": "CSV", "description": "字段配置",
            "fields": [{
                "fieldNameEn": "amount", "fieldNameCn": "金额", "semanticRole": "metric",
                "type": "decimal", "isPrimaryKey": True,
            }],
        }
        with self.assertRaisesRegex(ValueError, "raw_table_metadata_primary_key_must_be_dimension"):
            _validate_asset_schema("raw_table", invalid)


if __name__ == "__main__":
    unittest.main()

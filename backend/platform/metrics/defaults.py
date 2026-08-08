from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_default_metric_dictionary() -> list[dict[str, Any]]:
    seed_path = Path(__file__).resolve().parents[3] / "Origin_Data" / "metric_dictionary_seed.json"
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        return []
    return [dict(metric) for metric in metrics if isinstance(metric, dict)]


def teams_subscription_test_metrics() -> list[dict[str, Any]]:
    """Two deterministic system metrics used only for Teams connection tests."""
    return [
        {
            "metricId": "SYS_TEAMS_TEST_AMOUNT",
            "metricName": "【测试】经营金额",
            "definition": "仅用于 Teams 消息模板与连接测试的固定示例金额。",
            "metricCode": "sda_teams_test_amount",
            "datasetId": "sda_teams_test",
            "aggregationType": "sum",
            "semanticVersion": "1",
            "semanticStatus": "documentation",
            "unit": "万元",
            "statTime": "测试发送时生成",
            "description": "系统测试指标，不参与正式分析、周报或经营口径。",
            "systemSource": "系统测试",
            "visibleInstitutions": ["全部机构"],
            "visibleRoles": [],
            "isTestMetric": True,
        },
        {
            "metricId": "SYS_TEAMS_TEST_CUSTOMERS",
            "metricName": "【测试】活跃客户数",
            "definition": "仅用于 Teams 消息模板与连接测试的固定示例客户数。",
            "metricCode": "sda_teams_test_customers",
            "datasetId": "sda_teams_test",
            "aggregationType": "count",
            "semanticVersion": "1",
            "semanticStatus": "documentation",
            "unit": "户",
            "statTime": "测试发送时生成",
            "description": "系统测试指标，不参与正式分析、周报或经营口径。",
            "systemSource": "系统测试",
            "visibleInstitutions": ["全部机构"],
            "visibleRoles": [],
            "isTestMetric": True,
        },
    ]

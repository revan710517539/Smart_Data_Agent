from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from backend.platform.data_access import JSONDataWarehouse
from backend.platform.semantic import InMemorySupersonicClient


class GovernedTestWarehouse(JSONDataWarehouse):
    data_source_name = "governed_test_warehouse"

    def snapshot_info(self, dataset_id: str) -> dict[str, Any]:
        self._dataset(dataset_id)
        return {
            "snapshot_id": f"governed-test-v1-{dataset_id}",
            "observed_at": "2026-07-13T00:00:00Z",
            "latest_partition": "2026-07",
            "artifact_sha256": hashlib.sha256(dataset_id.encode("utf-8")).hexdigest(),
            "immutable": True,
        }


def build_governed_test_warehouse() -> JSONDataWarehouse:
    """Build an explicit test-only warehouse without enabling runtime fallback."""

    warehouse = GovernedTestWarehouse.__new__(GovernedTestWarehouse)
    warehouse.path = Path("<governed-test-warehouse>")
    warehouse._payload = {"version": "test-snapshot-v1"}
    warehouse._datasets = _datasets()
    return warehouse


def attach_governed_test_warehouse(services: Any) -> None:
    services.semantic_service.client = InMemorySupersonicClient(build_governed_test_warehouse())
    services.data_source_mode = "governed_test_warehouse"
    asset_store = getattr(services, "data_asset_store", None)
    if asset_store is None:
        return
    asset_store.upsert_item(
        "tenant_demo",
        "analysis_experience",
        {
            "id": "exp_weekly_growth_quality",
            "title": "周报增长质量分析经验",
            "steps": "先核对口径，再比较规模、转化和风险。",
            "enabled": True,
        },
        updated_by="test_fixture",
        lifecycle_status="active",
    )
    asset_store.upsert_item(
        "tenant_demo",
        "topic_table",
        {
            "id": "topic_weekly_branch_rank",
            "name": "分行放款排名分析",
            "code": "weekly_branch_loan_rank",
            "description": "按机构查看放款金额和动支率。",
            "datasetId": "loan_operation_mart",
            "metricCodes": ["loan_amount", "drawdown_rate"],
            "defaultMetrics": ["loan_amount"],
            "dimensionCodes": ["branch_name", "month"],
            "defaultDimensions": ["branch_name"],
            "chartTypes": ["bar", "table"],
            "analysisAngles": ["机构排名", "趋势"],
            "applicableScene": "经营周报",
            "sql": "SELECT branch_name, loan_amount FROM weekly_branch_loan_rank WHERE tenant_id = :tenant_id",
            "fields": [
                {"fieldNameEn": "branch_name", "fieldNameCn": "机构", "type": "string", "explanation": "经营机构"},
                {"fieldNameEn": "loan_amount", "fieldNameCn": "放款金额", "type": "decimal", "explanation": "实际放款本金"},
            ],
        },
        updated_by="test_fixture",
        lifecycle_status="active",
    )


def _datasets() -> dict[str, dict[str, Any]]:
    branches = ("上海分行", "深圳分行", "广州分行", "南京分行", "郑州分行", "成都分行", "杭州分行", "武汉分行", "苏州分行", "合肥分行")
    loan_rows = [
        {
            "tenant_id": "*",
            "branch_name": branch,
            "product_line": "经营贷" if index % 2 == 0 else "消费贷",
            "month": "2026-07",
            "channel": "客户经理" if index % 2 == 0 else "手机银行",
            "customer_segment": "小微商户" if index % 2 == 0 else "年轻白领",
            "loan_amount": float((10 - index) * 10_000_000),
            "drawdown_amount": float((10 - index) * 4_000_000),
            "eligible_amount": float((10 - index) * 8_000_000),
            "drawdown_rate": 0.5,
        }
        for index, branch in enumerate(branches)
    ]
    loan_rows.extend(
        [
            {
                "tenant_id": "*", "branch_name": "广州分行", "product_line": "经营贷",
                "month": "2026-06", "channel": "客户经理", "customer_segment": "存量经营户",
                "loan_amount": 29_400_000.0, "drawdown_amount": 16_550_000.0,
                "eligible_amount": 50_000_000.0, "drawdown_rate": 0.331,
            },
            {
                "tenant_id": "*", "branch_name": "成都分行", "product_line": "消费贷",
                "month": "2026-06", "channel": "联合运营", "customer_segment": "年轻白领",
                "loan_amount": 25_800_000.0, "drawdown_amount": 12_640_000.0,
                "eligible_amount": 40_000_000.0, "drawdown_rate": 0.316,
            },
            {
                "tenant_id": "*", "branch_name": "测试分行", "product_line": "经营贷",
                "month": "2026-06", "channel": "客户经理", "customer_segment": "小微商户",
                "loan_amount": 21_600_000.0, "drawdown_amount": 10_410_000.0,
                "eligible_amount": 30_000_000.0, "drawdown_rate": 0.347,
            },
        ]
    )
    funnel_rows = [
        {
            "tenant_id": "*",
            "branch_name": branch,
            "institution_name": branch,
            "product_name": "经营贷",
            "month": "2026-07",
            "application_order_count": 100 - index,
            "completion_order_count": 90 - index,
            "credit_approved_order_count": 80 - index,
            "drawdown_application_order_count": 70 - index,
            "drawdown_success_order_count": 60 - index,
            "completed_customer_count": 90 - index,
            "credit_approved_customer_count": 80 - index,
            "drawdown_success_customer_count": 60 - index,
            "credit_approval_rate": 0.8,
            "drawdown_rate": 0.75,
            "approved_amount": float((80 - index) * 100_000),
            "drawdown_amount": float((60 - index) * 100_000),
            "loan_balance": float((50 - index) * 100_000),
            "m1_overdue_balance": float((index + 1) * 1_000),
            "m1_overdue_rate": 0.01,
            "credit_rate_weighted_amount": float((80 - index) * 5_000),
            "credit_weighted_rate": 0.05,
            "drawdown_rate_weighted_amount": float((60 - index) * 4_000),
            "drawdown_weighted_rate": 0.04,
        }
        for index, branch in enumerate(branches)
    ]
    return {
        "weekly_core_metrics_mart": {
            "label": "经营周报核心指标",
            "allowed_metrics": ["loan_balance", "loan_amount", "new_balance"],
            "allowed_dimensions": ["stat_week"],
            "metric_aggregation": {"loan_balance": "sum", "loan_amount": "sum", "new_balance": "sum"},
            "rows": [
                {"tenant_id": "*", "stat_week": "2026-07-06", "loan_balance": 1_000_000, "loan_amount": 200_000, "new_balance": 20_000},
                {"tenant_id": "*", "stat_week": "2026-07-13", "loan_balance": 1_100_000, "loan_amount": 240_000, "new_balance": 30_000},
            ],
        },
        "loan_operation_mart": {
            "label": "贷款经营宽表",
            "allowed_metrics": ["loan_amount", "drawdown_rate"],
            "allowed_dimensions": ["branch_name", "product_line", "month", "channel", "customer_segment"],
            "metric_aggregation": {
                "loan_amount": "sum",
                "drawdown_rate": {"aggregation": "ratio", "numerator": "drawdown_amount", "denominator": "eligible_amount", "multiplier": 1},
            },
            "rows": loan_rows,
        },
        "risk_operation_mart": {
            "label": "风险经营宽表",
            "allowed_metrics": ["m1_overdue_rate", "loan_balance"],
            "allowed_dimensions": ["branch_name", "product_line", "month", "customer_segment"],
            "metric_aggregation": {
                "m1_overdue_rate": {"aggregation": "ratio", "numerator": "m1_overdue_balance", "denominator": "loan_balance", "multiplier": 1},
                "loan_balance": "sum",
            },
            "rows": [
                {**row, "m1_overdue_balance": row["loan_amount"] * 0.01, "loan_balance": row["loan_amount"] * 2, "m1_overdue_rate": 0.005}
                for row in loan_rows
            ],
        },
        "channel_operation_mart": {
            "label": "渠道经营宽表",
            "allowed_metrics": ["customer_acquisition_cost", "roi"],
            "allowed_dimensions": ["channel", "month", "product_line", "branch_name"],
            "metric_aggregation": {
                "customer_acquisition_cost": {"aggregation": "ratio", "numerator": "marketing_cost", "denominator": "new_customer_count", "multiplier": 1},
                "roi": {"aggregation": "ratio", "numerator": "attributed_revenue", "denominator": "marketing_cost", "multiplier": 1},
            },
            "rows": [
                {**row, "marketing_cost": 100_000 + index * 1_000, "new_customer_count": 1_000, "attributed_revenue": 250_000, "customer_acquisition_cost": 100 + index, "roi": 2.5}
                for index, row in enumerate(loan_rows)
            ],
        },
        "customer_operation_mart": {
            "label": "客群经营宽表",
            "allowed_metrics": ["conversion_rate", "active_customer_count"],
            "allowed_dimensions": ["customer_segment", "month", "product_line", "branch_name"],
            "metric_aggregation": {
                "conversion_rate": {"aggregation": "ratio", "numerator": "converted_customer_count", "denominator": "eligible_customer_count", "multiplier": 1},
                "active_customer_count": "sum",
            },
            "rows": [
                {**row, "converted_customer_count": 50 + index, "eligible_customer_count": 100, "conversion_rate": (50 + index) / 100, "active_customer_count": 80 + index}
                for index, row in enumerate(loan_rows)
            ],
        },
        "loan_funnel_mock_mart": {
            "label": "受治理贷款漏斗测试宽表",
            "allowed_metrics": [
                "application_order_count", "completion_order_count", "credit_approved_order_count",
                "drawdown_application_order_count", "drawdown_success_order_count", "credit_approval_rate",
                "drawdown_rate", "approved_amount", "drawdown_amount", "loan_balance", "m1_overdue_rate",
                "credit_weighted_rate", "drawdown_weighted_rate",
            ],
            "allowed_dimensions": ["branch_name", "institution_name", "product_name", "month"],
            "metric_aggregation": {
                "application_order_count": "sum", "completion_order_count": "sum",
                "credit_approved_order_count": "sum", "drawdown_application_order_count": "sum",
                "drawdown_success_order_count": "sum", "approved_amount": "sum", "drawdown_amount": "sum", "loan_balance": "sum",
                "credit_approval_rate": {"aggregation": "ratio", "numerator": "credit_approved_customer_count", "denominator": "completed_customer_count", "multiplier": 1},
                "drawdown_rate": {"aggregation": "ratio", "numerator": "drawdown_success_customer_count", "denominator": "credit_approved_customer_count", "multiplier": 1},
                "m1_overdue_rate": {"aggregation": "ratio", "numerator": "m1_overdue_balance", "denominator": "loan_balance", "multiplier": 1},
                "credit_weighted_rate": {"aggregation": "ratio", "numerator": "credit_rate_weighted_amount", "denominator": "approved_amount", "multiplier": 1},
                "drawdown_weighted_rate": {"aggregation": "ratio", "numerator": "drawdown_rate_weighted_amount", "denominator": "drawdown_amount", "multiplier": 1},
            },
            "rows": funnel_rows,
        },
        "funnel_operation_mart": {
            "label": "业务漏斗宽表",
            "allowed_metrics": ["stage_count"],
            "allowed_dimensions": ["product_line", "branch_name", "stage_code", "stage_name", "stage_order", "stat_date"],
            "metric_aggregation": {"stage_count": "sum"},
            "rows": [
                {
                    "tenant_id": "*", "product_line": "经营贷", "branch_name": "上海分行",
                    "stage_code": code, "stage_name": name, "stage_order": order,
                    "stat_date": "2026-07-13", "stage_count": count,
                }
                for order, (code, name, count) in enumerate(
                    (("application", "进件", 100), ("completed", "完件", 85), ("approved", "授信", 70), ("drawdown", "动支", 55)),
                    start=1,
                )
            ],
        },
    }

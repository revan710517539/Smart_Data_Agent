from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from backend.platform.semantic import SemanticQueryRequest


SNAPSHOT_QUERIES: dict[str, tuple[dict[str, Any], ...]] = {
    "dashboard": (
        {
            "key": "loan_operation",
            "dataset_id": "loan_operation_mart",
            "metrics": ("loan_amount", "drawdown_rate"),
            "dimensions": ("product_line", "branch_name", "month"),
            "question": "按产品、机构和月份汇总放款金额与动支率",
        },
        {
            "key": "loan_product_trend",
            "dataset_id": "loan_operation_mart",
            "metrics": ("loan_amount", "drawdown_rate"),
            "dimensions": ("product_line", "month"),
            "question": "按产品和月份汇总放款金额与动支率",
        },
        {
            "key": "risk_operation",
            "dataset_id": "risk_operation_mart",
            "metrics": ("m1_overdue_rate", "loan_balance"),
            "dimensions": ("product_line", "branch_name", "month"),
            "question": "按产品、机构和月份汇总余额与M1逾期率",
        },
        {
            "key": "risk_product_trend",
            "dataset_id": "risk_operation_mart",
            "metrics": ("m1_overdue_rate", "loan_balance"),
            "dimensions": ("product_line", "month"),
            "question": "按产品和月份汇总余额与M1逾期率",
        },
        {
            "key": "customer_operation",
            "dataset_id": "customer_operation_mart",
            "metrics": ("active_customer_count", "conversion_rate"),
            "dimensions": ("product_line", "branch_name", "month", "customer_segment"),
            "question": "按产品、机构、月份和客群汇总活跃客户与转化率",
        },
        {
            "key": "customer_product_trend",
            "dataset_id": "customer_operation_mart",
            "metrics": ("active_customer_count", "conversion_rate"),
            "dimensions": ("product_line", "month"),
            "question": "按产品和月份汇总活跃客户数与转化率",
        },
        {
            "key": "channel_operation",
            "dataset_id": "channel_operation_mart",
            "metrics": ("customer_acquisition_cost", "roi"),
            "dimensions": ("product_line", "branch_name", "month", "channel"),
            "question": "按产品、机构、月份和渠道汇总获客成本与ROI",
        },
    ),
    "customer_insight": (
        {
            "key": "customer_segments",
            "dataset_id": "customer_operation_mart",
            "metrics": ("active_customer_count", "conversion_rate"),
            "dimensions": ("customer_segment", "product_line"),
            "question": "按客群和产品汇总活跃客户与转化率",
        },
        {
            "key": "customer_segment_trend",
            "dataset_id": "customer_operation_mart",
            "metrics": ("active_customer_count", "conversion_rate"),
            "dimensions": ("customer_segment", "product_line", "month"),
            "question": "按客群、产品和月份汇总活跃客户与转化率",
        },
        {
            "key": "customer_branches",
            "dataset_id": "customer_operation_mart",
            "metrics": ("active_customer_count", "conversion_rate"),
            "dimensions": ("branch_name", "product_line"),
            "question": "按机构和产品汇总活跃客户与转化率",
        },
    ),
    "institution_supervision": (
        {
            "key": "loan_operation",
            "dataset_id": "loan_operation_mart",
            "metrics": ("loan_amount", "drawdown_rate"),
            "dimensions": ("branch_name", "product_line", "month"),
            "question": "按机构、产品和月份汇总放款金额与动支率",
        },
        {
            "key": "risk_operation",
            "dataset_id": "risk_operation_mart",
            "metrics": ("m1_overdue_rate", "loan_balance"),
            "dimensions": ("branch_name", "product_line", "month"),
            "question": "按机构、产品和月份汇总余额与M1逾期率",
        },
    ),
    "business_funnel": (
        {
            "key": "funnel_operation",
            "dataset_id": "funnel_operation_mart",
            "metrics": ("stage_count",),
            "dimensions": ("product_line", "branch_name", "stage_code", "stage_name", "stage_order", "stat_date"),
            "question": "按产品、机构和日期汇总各业务漏斗阶段人数",
        },
    ),
    "weekly_report": (
        {
            "key": "weekly_core_metrics",
            "dataset_id": "weekly_core_metrics_mart",
            "metrics": ("loan_balance", "loan_amount", "new_balance"),
            "dimensions": ("stat_week",),
            "question": "按周度获取在贷余额、放款金额和新增余额",
        },
    ),
}


class OperatingSnapshotService:
    def __init__(self, semantic_service: Any) -> None:
        self.semantic_service = semantic_service

    def build(self, view: str, tenant_id: str, user_id: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        specs = SNAPSHOT_QUERIES.get(view)
        if specs is None:
            raise ValueError("unsupported_operating_snapshot_view")
        requested_filters = {
            key: value for key, value in dict(filters or {}).items()
            if key in {"product_line", "branch_name", "month", "customer_segment", "channel", "stat_date"}
            and value not in (None, "", "all", "全部分行")
        }
        datasets: dict[str, Any] = {}
        for spec in specs:
            try:
                result = self.semantic_service.query(
                    SemanticQueryRequest(
                        question=str(spec["question"]),
                        tenant_id=tenant_id,
                        user_id=user_id,
                        dataset_id=str(spec["dataset_id"]),
                        metrics=tuple(spec["metrics"]),
                        dimensions=tuple(spec["dimensions"]),
                        filters=requested_filters,
                        limit=500,
                        context={"surface": view, "purpose": "operating_snapshot"},
                    )
                )
                datasets[str(spec["key"])] = _dataset_payload(result)
            except (KeyError, ValueError, PermissionError):
                datasets[str(spec["key"])] = {
                    "status": "unavailable",
                    "error_code": "dataset_unavailable_or_forbidden",
                    "rows": [],
                    "evidence": {"publishable": False, "data_mode": "unavailable"},
                }
        available = [item for item in datasets.values() if item["status"] == "ready"]
        modes = sorted({str(item["evidence"]["data_mode"]) for item in available})
        return {
            "view": view,
            "status": "ready" if len(available) == len(datasets) else "partial" if available else "unavailable",
            "data_modes": modes,
            "publishable": bool(available) and all(bool(item["evidence"]["publishable"]) for item in available),
            "datasets": datasets,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def build_authorized_dashboard(
        self,
        tenant_ids: tuple[str, ...],
        user_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Aggregate only the already-authorized tenant snapshots for the dashboard.

        Authorization intentionally belongs to the HTTP route.  This service
        receives only the approved tenant IDs and never discovers or scans
        tenants by itself.  Every row is labelled before it leaves the
        service, so equal branch names from two institutions cannot be mixed
        in the multi-institution UI.
        """
        approved = tuple(dict.fromkeys(str(item).strip() for item in tenant_ids if str(item).strip()))
        if not approved:
            raise PermissionError("dashboard_tenant_scope_empty")
        snapshots = [self.build("dashboard", tenant_id, user_id, filters) for tenant_id in approved]
        dataset_keys = tuple(SNAPSHOT_QUERIES["dashboard"][index]["key"] for index in range(len(SNAPSHOT_QUERIES["dashboard"])))
        datasets: dict[str, Any] = {}
        data_modes: set[str] = set()
        every_dataset_ready = True
        every_dataset_publishable = True
        for dataset_key in dataset_keys:
            rows: list[dict[str, Any]] = []
            evidence_ids: list[str] = []
            ready = 0
            publishable = True
            for tenant_id, snapshot in zip(approved, snapshots):
                dataset = dict(snapshot["datasets"].get(dataset_key) or {})
                evidence = dict(dataset.get("evidence") or {})
                if dataset.get("status") == "ready":
                    ready += 1
                    data_modes.add(str(evidence.get("data_mode") or "unknown"))
                    evidence_ids.append(str(evidence.get("evidence_id") or ""))
                    publishable = publishable and bool(evidence.get("publishable"))
                    rows.extend(_label_dashboard_rows(dataset.get("rows"), tenant_id))
                else:
                    publishable = False
            status = "ready" if ready == len(approved) else "partial" if ready else "unavailable"
            every_dataset_ready = every_dataset_ready and status == "ready"
            every_dataset_publishable = every_dataset_publishable and publishable and status == "ready"
            datasets[dataset_key] = {
                "status": status,
                "rows": rows,
                "query": {"row_count": len(rows), "tenant_count": len(approved)},
                "evidence": {
                    "evidence_id": "multi_" + hashlib.sha256("|".join(sorted(evidence_ids)).encode("utf-8")).hexdigest()[:24],
                    "data_source": "authorized_tenant_aggregate",
                    "data_mode": "real" if data_modes == {"real"} else "mock" if data_modes == {"mock"} else "mixed" if data_modes else "unavailable",
                    "publishable": publishable and status == "ready",
                    "aggregation_semantics_complete": True,
                    "policy_enforced_at_source": True,
                    "tenant_count": len(approved),
                },
            }
        return {
            "view": "dashboard",
            "scope": "authorized_tenants",
            "tenant_ids": list(approved),
            "status": "ready" if every_dataset_ready else "partial" if any(item["status"] != "unavailable" for item in datasets.values()) else "unavailable",
            "data_modes": sorted(data_modes),
            "publishable": every_dataset_publishable,
            "datasets": datasets,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def _dataset_payload(result: Any) -> dict[str, Any]:
    semantic = dict(result.semantic_info or {})
    execution_mode = str(semantic.get("execution_mode") or "").lower()
    data_source = str(semantic.get("data_source") or "unknown")
    mock = execution_mode == "mock" or "mock" in data_source.lower()
    rows = [dict(row) for row in result.data]
    material = {
        "sql": result.sql,
        "parameters": result.parameters,
        "rows": rows,
        "source_snapshot": semantic.get("source_snapshot"),
    }
    return {
        "status": "ready",
        "rows": rows,
        "query": {
            "sql_hash": hashlib.sha256(str(result.sql).encode("utf-8")).hexdigest(),
            "parameters": dict(result.parameters or {}),
            "row_count": len(rows),
        },
        "evidence": {
            "evidence_id": "snap_" + hashlib.sha256(
                json.dumps(material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:24],
            "data_source": data_source,
            "data_mode": "mock" if mock else "real",
            "publishable": bool(semantic.get("publishable", not mock)) and not mock,
            "source_snapshot": semantic.get("source_snapshot") if isinstance(semantic.get("source_snapshot"), dict) else {},
            "aggregation_semantics_complete": bool(semantic.get("aggregation_semantics_complete")),
            "policy_enforced_at_source": bool(semantic.get("policy_enforced_at_source")),
            "provider_query_id": str(semantic.get("provider_query_id") or ""),
        },
    }


def _label_dashboard_rows(value: Any, tenant_id: str) -> list[dict[str, Any]]:
    institution = str(tenant_id).split(":", 1)[-1] or tenant_id
    rows: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        branch = str(row.get("branch_name") or "").strip()
        row["institution_name"] = institution
        if branch:
            row["branch_name"] = f"{institution} · {branch}"
        rows.append(row)
    return rows

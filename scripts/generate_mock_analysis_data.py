#!/usr/bin/env python3
"""Generate deterministic, relational mock fixtures for governed analysis.

The generated values are synthetic.  The validator fails closed on row counts,
keys, lifecycle dates, amount constraints, and metric numerator/denominator
relationships so the fixtures can be safely used for semantic-analysis tests.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "mock"
INSTITUTION_PATH = OUTPUT_DIR / "institution_master_100.csv"
CUSTOMER_PATH = OUTPUT_DIR / "customer_master_100.csv"
ORDER_PATH = OUTPUT_DIR / "loan_transaction_order_100.csv"
QUALITY_PATH = OUTPUT_DIR / "mock_data_quality_report.json"

CITIES = (
    ("上海", "上海市"), ("南京", "江苏省"), ("苏州", "江苏省"), ("杭州", "浙江省"),
    ("深圳", "广东省"), ("广州", "广东省"), ("成都", "四川省"), ("武汉", "湖北省"),
    ("郑州", "河南省"), ("合肥", "安徽省"),
)
SEGMENTS = ("小微商户", "存量经营户", "年轻白领", "代发客群", "新市民")
INDUSTRIES = ("制造业", "批发零售", "信息技术", "餐饮服务", "商务服务")
PRODUCTS = ("经营贷", "消费贷", "综合授信")
CHANNELS = ("客户经理", "手机银行", "联合运营", "线上渠道")

INSTITUTION_FIELDS = (
    "tenant_id", "institution_id", "institution_code", "institution_name", "institution_level",
    "parent_institution_id", "branch_name", "province", "city", "institution_type", "opening_date",
    "employee_count", "customer_manager_count", "target_application_count", "target_credit_amount",
    "target_drawdown_amount", "status",
)
CUSTOMER_FIELDS = (
    "tenant_id", "customer_id", "customer_name", "gender", "age", "province", "city",
    "customer_segment", "industry", "institution_id", "institution_name", "branch_name",
    "customer_manager_id", "customer_manager_name", "registration_date", "annual_income",
    "annual_revenue", "credit_score", "risk_level", "is_active", "has_credit",
    "has_drawdown", "current_loan_balance",
)
ORDER_FIELDS = (
    "tenant_id", "order_id", "customer_id", "institution_id", "institution_name", "branch_name",
    "product_line", "channel", "customer_segment", "application_date", "completion_date",
    "decision_date", "credit_approved_date", "drawdown_application_date", "drawdown_date", "month",
    "current_stage", "application_status", "application_amount", "approved_amount",
    "drawdown_apply_amount", "drawdown_amount", "loan_balance", "m1_overdue_balance",
    "overdue_days", "annual_interest_rate", "term_months", "application_order_count",
    "completion_order_count", "completed_customer_count", "credit_approved_order_count",
    "credit_approved_customer_count", "drawdown_application_order_count",
    "drawdown_success_order_count", "drawdown_success_customer_count", "credit_rate_weighted_amount",
    "drawdown_rate_weighted_amount",
)


def generate() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    institutions = _institutions()
    customers = _customers(institutions)
    orders = _orders(customers)
    order_by_customer = {row["customer_id"]: row for row in orders}
    for customer in customers:
        order = order_by_customer[customer["customer_id"]]
        customer["has_credit"] = order["credit_approved_customer_count"]
        customer["has_drawdown"] = order["drawdown_success_customer_count"]
        customer["current_loan_balance"] = order["loan_balance"]
    return institutions, customers, orders


def _institutions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, 101):
        branch_index = (index - 1) // 10
        position = (index - 1) % 10
        city, province = CITIES[branch_index]
        branch_id = f"INST{branch_index * 10 + 1:03d}"
        is_branch = position == 0
        institution_id = f"INST{index:03d}"
        branch_name = f"{city}分行"
        rows.append({
            "tenant_id": "*",
            "institution_id": institution_id,
            "institution_code": f"ORG{index:04d}",
            "institution_name": branch_name if is_branch else f"{city}第{position:02d}支行",
            "institution_level": "分行" if is_branch else "支行",
            "parent_institution_id": "" if is_branch else branch_id,
            "branch_name": branch_name,
            "province": province,
            "city": city,
            "institution_type": "一级分行" if is_branch else ("综合支行" if position % 2 else "小微专营支行"),
            "opening_date": str(date(2008, 1, 1) + timedelta(days=index * 41)),
            "employee_count": 80 + branch_index * 6 if is_branch else 12 + position * 2,
            "customer_manager_count": 18 + branch_index if is_branch else 3 + position % 5,
            "target_application_count": 180 + index * 3,
            "target_credit_amount": 8_000_000 + index * 250_000,
            "target_drawdown_amount": 5_000_000 + index * 180_000,
            "status": "正常",
        })
    return rows


def _customers(institutions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["institution_id"]: row for row in institutions}
    rows: list[dict[str, Any]] = []
    for index in range(1, 101):
        branch_index = (index - 1) % 10
        leaf_position = ((index * 7) % 9) + 2
        institution = by_id[f"INST{branch_index * 10 + leaf_position:03d}"]
        age = 23 + (index * 7) % 39
        score = 560 + (index * 17) % 250
        rows.append({
            "tenant_id": "*",
            "customer_id": f"CUST{index:04d}",
            "customer_name": f"模拟客户{index:03d}",
            "gender": "男" if index % 2 else "女",
            "age": age,
            "province": institution["province"],
            "city": institution["city"],
            "customer_segment": SEGMENTS[(index - 1) % len(SEGMENTS)],
            "industry": INDUSTRIES[(index * 3) % len(INDUSTRIES)],
            "institution_id": institution["institution_id"],
            "institution_name": institution["institution_name"],
            "branch_name": institution["branch_name"],
            "customer_manager_id": f"RM{(index - 1) % 30 + 1:03d}",
            "customer_manager_name": f"客户经理{(index - 1) % 30 + 1:02d}",
            "registration_date": str(date(2024, 1, 1) + timedelta(days=index * 6)),
            "annual_income": 90_000 + index * 3_500,
            "annual_revenue": 300_000 + index * 28_000,
            "credit_score": score,
            "risk_level": "低" if score >= 700 else ("中" if score >= 620 else "高"),
            "is_active": 0 if index % 9 == 0 else 1,
            "has_credit": 0,
            "has_drawdown": 0,
            "current_loan_balance": 0,
        })
    return rows


def _orders(customers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approved_indices = [index for index in range(1, 101) if (index * 37) % 100 < 72]
    ranked_approved = sorted(approved_indices, key=lambda index: (index * 29) % 103)
    drawdown_success = set(ranked_approved[:52])
    drawdown_failed = set(ranked_approved[52:62])
    approved = set(approved_indices)
    rows: list[dict[str, Any]] = []
    for index, customer in enumerate(customers, start=1):
        application_date = date(2026, 1, 2) + timedelta(days=(index * 2) % 178)
        completion_date = application_date + timedelta(days=index % 3)
        is_approved = index in approved
        pending = not is_approved and (index * 37) % 100 < 82
        decision_date = None if pending else completion_date + timedelta(days=1 + index % 4)
        approved_date = decision_date if is_approved else None
        draw_applied = index in drawdown_success or index in drawdown_failed
        draw_apply_date = approved_date + timedelta(days=1 + index % 5) if draw_applied and approved_date else None
        draw_date = draw_apply_date + timedelta(days=1 + index % 3) if index in drawdown_success and draw_apply_date else None
        application_amount = 80_000 + index * 12_500
        approved_amount = int(application_amount * (0.70 + (index % 6) * 0.04)) // 1000 * 1000 if is_approved else 0
        draw_apply_amount = int(approved_amount * (0.55 + (index % 5) * 0.07)) // 1000 * 1000 if draw_applied else 0
        drawdown_amount = draw_apply_amount if index in drawdown_success else 0
        repaid_amount = int(drawdown_amount * ((index % 4) * 0.08)) // 100 * 100
        loan_balance = drawdown_amount - repaid_amount
        overdue_days = 30 + index % 25 if drawdown_amount and index % 11 == 0 else 0
        m1_overdue_balance = min(loan_balance, int(loan_balance * 0.35)) if overdue_days else 0
        annual_interest_rate = round(0.035 + (index % 13) * 0.0025, 4)
        if index in drawdown_success:
            stage, status = "动支", "动支成功"
        elif index in drawdown_failed:
            stage, status = "动支", "动支处理中"
        elif is_approved:
            stage, status = "授信", "授信成功待动支"
        elif pending:
            stage, status = "完件", "审批中"
        else:
            stage, status = "授信", "授信拒绝"
        rows.append({
            "tenant_id": "*",
            "order_id": f"LOAN{index:05d}",
            "customer_id": customer["customer_id"],
            "institution_id": customer["institution_id"],
            "institution_name": customer["institution_name"],
            "branch_name": customer["branch_name"],
            "product_line": PRODUCTS[(index - 1) % len(PRODUCTS)],
            "channel": CHANNELS[(index * 3) % len(CHANNELS)],
            "customer_segment": customer["customer_segment"],
            "application_date": str(application_date),
            "completion_date": str(completion_date),
            "decision_date": str(decision_date) if decision_date else "",
            "credit_approved_date": str(approved_date) if approved_date else "",
            "drawdown_application_date": str(draw_apply_date) if draw_apply_date else "",
            "drawdown_date": str(draw_date) if draw_date else "",
            "month": str(application_date)[:7],
            "current_stage": stage,
            "application_status": status,
            "application_amount": application_amount,
            "approved_amount": approved_amount,
            "drawdown_apply_amount": draw_apply_amount,
            "drawdown_amount": drawdown_amount,
            "loan_balance": loan_balance,
            "m1_overdue_balance": m1_overdue_balance,
            "overdue_days": overdue_days,
            "annual_interest_rate": annual_interest_rate,
            "term_months": 12 + (index % 4) * 12,
            "application_order_count": 1,
            "completion_order_count": 1,
            "completed_customer_count": 1,
            "credit_approved_order_count": int(is_approved),
            "credit_approved_customer_count": int(is_approved),
            "drawdown_application_order_count": int(draw_applied),
            "drawdown_success_order_count": int(index in drawdown_success),
            "drawdown_success_customer_count": int(index in drawdown_success),
            "credit_rate_weighted_amount": round(approved_amount * annual_interest_rate, 2),
            "drawdown_rate_weighted_amount": round(drawdown_amount * annual_interest_rate, 2),
        })
    return rows


def validate(
    institutions: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    for label, rows, key in (
        ("institutions", institutions, "institution_id"),
        ("customers", customers, "customer_id"),
        ("orders", orders, "order_id"),
    ):
        if len(rows) != 100:
            errors.append(f"{label}_row_count:{len(rows)}")
        if len({str(row[key]) for row in rows}) != len(rows):
            errors.append(f"{label}_duplicate_key")
    institution_by_id = {row["institution_id"]: row for row in institutions}
    customer_by_id = {row["customer_id"]: row for row in customers}
    for row in institutions:
        parent = str(row["parent_institution_id"])
        if parent and parent not in institution_by_id:
            errors.append(f"institution_parent_missing:{row['institution_id']}")
    for row in customers:
        institution = institution_by_id.get(row["institution_id"])
        if not institution:
            errors.append(f"customer_institution_missing:{row['customer_id']}")
        elif (row["institution_name"], row["branch_name"]) != (institution["institution_name"], institution["branch_name"]):
            errors.append(f"customer_institution_denormalized_mismatch:{row['customer_id']}")
    for row in orders:
        customer = customer_by_id.get(row["customer_id"])
        if not customer or row["institution_id"] != customer["institution_id"]:
            errors.append(f"order_customer_institution_mismatch:{row['order_id']}")
        dates = [row[field] for field in ("application_date", "completion_date", "decision_date", "drawdown_application_date", "drawdown_date") if row[field]]
        if dates != sorted(dates):
            errors.append(f"order_date_sequence:{row['order_id']}")
        if not (0 <= float(row["drawdown_amount"]) <= float(row["approved_amount"]) <= float(row["application_amount"])):
            errors.append(f"order_amount_sequence:{row['order_id']}")
        if not (0 <= float(row["loan_balance"]) <= float(row["drawdown_amount"])):
            errors.append(f"order_balance_sequence:{row['order_id']}")
        if not (0 <= float(row["m1_overdue_balance"]) <= float(row["loan_balance"])):
            errors.append(f"order_overdue_sequence:{row['order_id']}")
        if bool(row["credit_approved_order_count"]) != bool(row["approved_amount"]):
            errors.append(f"order_approval_flag:{row['order_id']}")
        if bool(row["drawdown_success_order_count"]) != bool(row["drawdown_amount"]):
            errors.append(f"order_drawdown_flag:{row['order_id']}")
    metrics = {
        "application_order_count": sum(int(row["application_order_count"]) for row in orders),
        "completion_order_count": sum(int(row["completion_order_count"]) for row in orders),
        "credit_approved_order_count": sum(int(row["credit_approved_order_count"]) for row in orders),
        "drawdown_application_order_count": sum(int(row["drawdown_application_order_count"]) for row in orders),
        "drawdown_success_order_count": sum(int(row["drawdown_success_order_count"]) for row in orders),
        "approved_amount": sum(int(row["approved_amount"]) for row in orders),
        "drawdown_amount": sum(int(row["drawdown_amount"]) for row in orders),
        "loan_balance": sum(int(row["loan_balance"]) for row in orders),
    }
    metrics["credit_approval_rate"] = round(metrics["credit_approved_order_count"] / metrics["completion_order_count"], 6)
    metrics["drawdown_rate"] = round(metrics["drawdown_success_order_count"] / metrics["credit_approved_order_count"], 6)
    metrics["m1_overdue_rate"] = round(
        sum(int(row["m1_overdue_balance"]) for row in orders) / metrics["loan_balance"], 6
    ) if metrics["loan_balance"] else 0
    if errors:
        raise ValueError("mock_data_validation_failed:\n" + "\n".join(errors[:50]))
    return {
        "status": "passed",
        "version": "2026-07-11",
        "row_counts": {"institutions": len(institutions), "customers": len(customers), "loan_orders": len(orders)},
        "metric_reconciliation": metrics,
        "checks": [
            "unique_primary_keys", "foreign_keys", "institution_denormalization", "lifecycle_date_order",
            "drawdown_le_credit_le_application", "m1_le_balance_le_drawdown", "stage_flag_amount_consistency",
            "ratio_recomputed_from_numerator_denominator",
        ],
    }


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.validate_only:
        institutions, customers, orders = _read_csv(INSTITUTION_PATH), _read_csv(CUSTOMER_PATH), _read_csv(ORDER_PATH)
    else:
        institutions, customers, orders = generate()
        _write_csv(INSTITUTION_PATH, INSTITUTION_FIELDS, institutions)
        _write_csv(CUSTOMER_PATH, CUSTOMER_FIELDS, customers)
        _write_csv(ORDER_PATH, ORDER_FIELDS, orders)
    quality = validate(institutions, customers, orders)
    QUALITY_PATH.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(quality, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

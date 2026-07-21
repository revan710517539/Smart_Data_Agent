"""Read-only synchronisation of Yushu's "My queries" SQL catalogue.

The implementation deliberately never sends ``batch-execute`` or another SQL
execution endpoint.  It uses the same authenticated page session as a user,
reads the catalogue API once, and registers each saved query as metadata for a
raw-table asset in Data Agent.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.platform.crawler_engine.systems.qifu_focuspro_sios.auto_login import (
    ensure_business_sandbox_login_session,
)


YUSHU_MY_QUERIES_PROFILE_ID = "qifu_yushu.my_queries.v1"
YUSHU_TOOL_ID = "tool_yushu_my_queries_sync"


def fetch_my_queries(
    *,
    connection: dict[str, Any],
    page_url: str,
    storage_state: Path,
    browser_channel: str = "chrome",
) -> list[dict[str, Any]]:
    """Return every folder and saved SQL visible in the authenticated account.

    The page API has no pagination and accepts an empty ``keyWord`` to return
    every folder.  Reusing the normal CAS session avoids opening a visible
    browser and keeps authentication logic in one maintained place.
    """

    ensure_business_sandbox_login_session(
        connection=connection,
        page_url=page_url,
        storage_state=storage_state,
        browser_channel=browser_channel,
    )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=browser_channel)
        context = browser.new_context(
            storage_state=str(storage_state),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        try:
            page = context.new_page()
            page.goto(page_url, wait_until="networkidle", timeout=60_000)
            payload = page.evaluate(
                """async () => {
                    const response = await fetch('/bolt/api/ad-hoc-query/sql/list', {
                      method: 'POST',
                      headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({keyWord: ''}),
                    });
                    return {status: response.status, body: await response.json()};
                }"""
            )
        finally:
            context.close()
            browser.close()

    if not isinstance(payload, dict) or int(payload.get("status") or 0) != 200:
        raise RuntimeError("yushu_my_queries_request_failed")
    response_body = payload.get("body")
    if not isinstance(response_body, dict) or str(response_body.get("flag") or "").upper() != "S":
        message = str((response_body or {}).get("msg") or "unknown_error")
        raise RuntimeError(f"yushu_my_queries_response_failed:{message[:240]}")

    queries: list[dict[str, Any]] = []
    for group in response_body.get("data") or []:
        if not isinstance(group, dict):
            continue
        folder_name = str(group.get("groupName") or "default").strip() or "default"
        folder_id = str(group.get("id") or "").strip()
        # The API uses ``rowList``; ``children`` preserves compatibility with
        # older installations of the Yushu front end.
        for query in group.get("rowList") or group.get("children") or []:
            if not isinstance(query, dict):
                continue
            sql = str(query.get("content") or "").strip()
            query_name = str(query.get("name") or "").strip()
            query_id = str(query.get("id") or "").strip()
            if not query_name or not query_id or not sql:
                continue
            queries.append(
                {
                    "folderId": folder_id,
                    "folderName": folder_name,
                    "queryId": query_id,
                    "queryName": query_name,
                    "sql": sql,
                    "dataCenter": str(query.get("dataCenter") or "").strip(),
                    "queryEngine": str(query.get("queryEngine") or "").strip(),
                    "dataSource": str(query.get("dataSource") or "").strip(),
                    "dateUpdated": query.get("dateUpdated"),
                    "dateCreated": query.get("dateCreated"),
                }
            )
    return queries


def sync_my_queries_to_raw_tables(
    *,
    data_asset_store: Any,
    tenant_id: str,
    actor_user_id: str,
    connection: dict[str, Any],
    page_url: str,
    storage_state: Path,
    browser_channel: str = "chrome",
) -> dict[str, Any]:
    """Fetch and upsert Yushu SQL metadata as independent raw-table records."""

    queries = fetch_my_queries(
        connection=connection,
        page_url=page_url,
        storage_state=storage_state,
        browser_channel=browser_channel,
    )
    saved_ids: list[str] = []
    for query in queries:
        item = _raw_table_asset(query=query, connection=connection)
        data_asset_store.upsert_item(
            tenant_id,
            "raw_table",
            item,
            updated_by=actor_user_id,
            lifecycle_status="active",
        )
        saved_ids.append(item["id"])
    return {
        "profile_id": YUSHU_MY_QUERIES_PROFILE_ID,
        "folders": len({query["folderId"] for query in queries}),
        "queries": len(queries),
        "raw_table_ids": saved_ids,
        "operation": "metadata_sync_only",
    }


def _raw_table_asset(*, query: dict[str, Any], connection: dict[str, Any]) -> dict[str, Any]:
    query_id = str(query["queryId"])
    folder_name = str(query["folderName"])
    query_name = str(query["queryName"])
    sql = str(query["sql"])
    source_tables = _source_tables(sql)
    columns = _select_columns(sql)
    observed_at = datetime.now(timezone.utc).isoformat()
    stable_name = _identifier(f"yushu_{folder_name}_{query_id}", f"yushu_sql_{query_id}")
    return {
        "id": f"raw_yushu_sql_{query_id}",
        "tableNameEn": stable_name,
        "tableNameCn": f"{folder_name}-{query_name}",
        "source": "毓数",
        "sourcePlatform": "毓数",
        "linkedToolId": YUSHU_TOOL_ID,
        "tableType": "yushu_sql",
        "primaryKey": _find_field(columns, ("id", "no", "编号", "单号")),
        "dateField": _find_field(columns, ("date", "time", "日期", "时间")),
        "orgField": _find_field(columns, ("org", "branch", "机构", "分行")),
        "customerField": _find_field(columns, ("customer", "cust", "客户")),
        "description": (
            f"同步自毓数“我的查询”目录“{folder_name}”的 SQL“{query_name}”；"
            f"查询引擎：{query.get('queryEngine') or '未标注'}；"
            f"来源表：{', '.join(source_tables[:12]) or 'SQL 中未识别到实体表'}。"
        ),
        "updateFrequency": "随毓数 SQL 同步更新",
        "restrictions": "仅保存已授权账号可见的 SQL 元数据；同步过程不执行 SQL，调用毓数时沿用数据连接权限。",
        "exampleSql": sql,
        "fields": columns,
        "updatedAt": observed_at,
        "crawlerProfileId": YUSHU_MY_QUERIES_PROFILE_ID,
        "connectionId": str(connection.get("id") or ""),
        "yushuFolderId": str(query.get("folderId") or ""),
        "yushuFolderName": folder_name,
        "yushuQueryId": query_id,
        "yushuQueryName": query_name,
        "yushuDataCenter": str(query.get("dataCenter") or ""),
        "yushuQueryEngine": str(query.get("queryEngine") or ""),
        "yushuDataSource": str(query.get("dataSource") or ""),
        "sourceTables": source_tables,
        "sqlContentHash": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "usageScenario": "毓数 SQL 元数据管理、智能分析数据调用",
        "relatedIntent": "数据管理 / 毓数查询同步",
    }


def _select_columns(sql: str) -> list[dict[str, Any]]:
    """Infer outer SELECT output columns without attempting to execute SQL."""

    try:
        import sqlglot
        from sqlglot import exp

        statement = sqlglot.parse_one(sql, read="hive")
        select = statement.find(exp.Select)
        if select is not None:
            fields: list[dict[str, Any]] = []
            used: set[str] = set()
            for index, expression in enumerate(select.expressions, start=1):
                label = str(expression.alias_or_name or "").strip()
                if not label or label == "*":
                    label = str(expression.output_name or "").strip() or f"字段{index}"
                field_name = _unique_identifier(_identifier(label, f"field_{index}"), used)
                fields.append(_field(field_name, label, expression.sql(dialect="hive")))
            if fields:
                return fields
    except Exception:
        # A malformed saved statement should not prevent the rest of a user's
        # catalogue from syncing.  The conservative fallback below still
        # records one usable metadata field.
        pass
    return [_field("result_value", "查询结果", "")]


def _source_tables(sql: str) -> list[str]:
    try:
        import sqlglot
        from sqlglot import exp

        statement = sqlglot.parse_one(sql, read="hive")
        tables = [table.sql(dialect="hive") for table in statement.find_all(exp.Table)]
        return list(dict.fromkeys(table for table in tables if table))[:50]
    except Exception:
        matches = re.findall(r"\b(?:from|join)\s+([`\w.]+)", sql, flags=re.IGNORECASE)
        return list(dict.fromkeys(match.strip("`") for match in matches if match))[:50]


def _field(field_name: str, label: str, expression: str) -> dict[str, Any]:
    lowered = f"{field_name} {label} {expression}".lower()
    is_time = any(token in lowered for token in ("date", "time", "日期", "时间"))
    is_metric = any(
        token in lowered
        for token in ("sum(", "count(", "avg(", "amount", "balance", "rate", "金额", "余额", "率", "数量", "人数")
    )
    field_type = "date" if is_time else ("decimal" if is_metric else "string")
    return {
        "fieldNameEn": field_name,
        "fieldNameCn": label,
        "type": field_type,
        "explanation": "根据毓数 SQL 的最外层 SELECT 字段自动推断；执行前以毓数实际返回结构为准。",
        "isTime": is_time,
        "isMetric": is_metric,
        "metricLogic": expression if is_metric else "",
        "exampleUsage": "毓数平台授权查询、智能分析数据调用",
    }


def _find_field(fields: list[dict[str, Any]], tokens: tuple[str, ...]) -> str:
    for field in fields:
        value = f"{field.get('fieldNameEn', '')} {field.get('fieldNameCn', '')}".lower()
        if any(token.lower() in value for token in tokens):
            return str(field.get("fieldNameEn") or "")
    return ""


def _identifier(value: str, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
    if not text or not re.match(r"[A-Za-z_]", text):
        text = fallback
    return text[:180]


def _unique_identifier(value: str, used: set[str]) -> str:
    base = value
    suffix = 2
    while value in used:
        value = f"{base}_{suffix}"
        suffix += 1
    used.add(value)
    return value

"""Registry entries that expose maintained crawler capabilities as tools."""

from __future__ import annotations

from typing import Any


FOCUSPRO_TOOL_ID = "tool_focuspro_business_sandbox_crawler"
FOCUSPRO_FUNNEL_TOOL_ID = "tool_focuspro_funnel_analysis_crawler"
YUSHU_TOOL_ID = "tool_yushu_my_queries_sync"


def ensure_crawler_tools(data_asset_store: Any, tenant_id: str, *, updated_by: str = "system") -> None:
    """Create the two built-in crawler tools once without overwriting user edits."""

    tools = (
        {
            "id": FOCUSPRO_TOOL_ID,
            "name": "华兴银行经营沙盘数据获取",
            "provider": "智能运营",
            "toolType": "crawler",
            "description": "无界面登录 FocusPro SIOS 经营沙盘，采集经营沙盘与经营明细，并由自动化任务控制启停和每天执行时间。",
            "endpoint": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/businessSandbox",
            "capabilities": ["经营沙盘", "经营明细", "自动定时执行", "启停与时间配置"],
            "enabled": True,
            "status": "已接入",
            "automationTaskCode": "crawler_url_7fb4c66ef5bd49e471ea4e5c",
        },
        {
            "id": FOCUSPRO_FUNNEL_TOOL_ID,
            "name": "华兴银行漏斗分析数据获取",
            "provider": "智能运营",
            "toolType": "crawler",
            "description": "无界面登录 FocusPro SIOS 漏斗分析页，通过前端加密 API 采集机构指标、节点指标、趋势和漏损明细。",
            "endpoint": "https://ghbank-focuspro-sios.qifu.tech/portal-h5/index.html#/sios/funnelAnalysis",
            "capabilities": ["模拟登录", "验证码识别", "漏斗指标", "趋势采集", "漏损明细"],
            "enabled": True,
            "status": "已接入",
            "automationTaskCode": "crawler_url_5faed19c5b4e5091ae30f1fb",
        },
        {
            "id": YUSHU_TOOL_ID,
            "name": "华兴毓数我的查询 SQL 同步",
            "provider": "毓数",
            "toolType": "crawler",
            "description": "无界面登录毓数自助查询，遍历“我的查询”全部文件夹并同步 SQL 元数据为原始表；不会执行 SQL。",
            "endpoint": "https://union-yushu.qifu.tech/bolt/dataQuery",
            "capabilities": ["目录遍历", "SQL 元数据同步", "原始表建表", "权限继承"],
            "enabled": True,
            "status": "已接入",
        },
    )
    for tool in tools:
        if data_asset_store.get_item(tenant_id, "external_tool", tool["id"]) is None:
            data_asset_store.upsert_item(
                tenant_id,
                "external_tool",
                tool,
                updated_by=updated_by,
                lifecycle_status="active",
            )

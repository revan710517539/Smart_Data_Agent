from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.authz.seed import OPERATING_TENANTS
from backend.platform.memory.fusion import MEMORY_ASSET_TYPES, prepare_asset_fusion
from backend.platform.storage import connect_sqlite
from .mock_analysis_defaults import MOCK_RAW_TABLES, MOCK_TOPIC_TABLES


ASSET_TYPES = {
    "raw_table", "topic_table", "intent", "analysis_experience", "knowledge_file", "user_behavior_habit",
    "analysis_skill", "external_tool", "analysis_shortcut", "page_data", "table_relationship", "conclusion_rule",
}
ASSET_LIFECYCLE_STATUSES = {"draft", "review", "active", "rejected", "archived"}
ASSET_BUNDLE_KEYS = {
    "raw_table": "raw_tables",
    "topic_table": "topic_tables",
    "intent": "intents",
    "analysis_experience": "analysis_experiences",
    "user_behavior_habit": "behavior_habits",
    "knowledge_file": "knowledge_files",
    "analysis_skill": "analysis_skills",
    "external_tool": "external_tools",
    "analysis_shortcut": "analysis_shortcuts",
    "page_data": "page_data",
    "table_relationship": "table_relationships",
    "conclusion_rule": "conclusion_rules",
}

SCENE_INTENT_SKILL_ID = "scene-analysis-intent"
SCENE_CHART_FOLLOWUP_SKILL_ID = "scene-chart-followup"
SCENE_PAGE_RAIL_SKILL_ID = "scene-page-rail"
SCENE_TEXTBOX_VOICE_SKILL_ID = "scene-textbox-voice"
SCENE_SELF_ANALYSIS_SKILL_ID = "scene-self-analysis"
CORE_TOPIC_SKILL_IDS = ("topic-descriptive", "topic-attribution", "topic-predictive")
CORE_TOPIC_SKILL_LABELS = {
    "topic-descriptive": "描述性分析",
    "topic-attribution": "归因分析",
    "topic-predictive": "预测分析",
}
DISPATCH_SCENE_SKILL_IDS = (
    "scene-weekly-report",
    "scene-daily-operation",
    "scene-risk-strategy",
)
DISPATCH_TOPIC_SKILL_IDS = (
    "topic-exploratory",
    "topic-financial-budget",
    "topic-credit-risk",
    "topic-suspicious-transaction",
    "topic-liquidity-risk",
    "topic-overdue-risk",
)
PLATFORM_ANALYSIS_SKILL_IDS = (
    SCENE_INTENT_SKILL_ID,
    SCENE_CHART_FOLLOWUP_SKILL_ID,
    SCENE_PAGE_RAIL_SKILL_ID,
    SCENE_TEXTBOX_VOICE_SKILL_ID,
    SCENE_SELF_ANALYSIS_SKILL_ID,
    *CORE_TOPIC_SKILL_IDS,
    *DISPATCH_SCENE_SKILL_IDS,
    *DISPATCH_TOPIC_SKILL_IDS,
)
PLATFORM_TOOL_IDS = (
    "tool-confluence-search",
    "tool-outlook",
    "tool-teams-cloud-doc",
    "tool-teams-t5t",
    "tool-financial-analyst",
)
PLATFORM_INTENT_IDS = ("intent_branch_rank", "intent_risk_diagnosis")
PLATFORM_EXPERIENCE_IDS = ("exp_weekly_growth_quality", "exp_m1_risk_check")
PLATFORM_VISIBLE_ANALYSIS_SKILL_IDS = frozenset(PLATFORM_ANALYSIS_SKILL_IDS)
PLATFORM_VISIBLE_CATALOG_IDS = frozenset(
    (
        *PLATFORM_ANALYSIS_SKILL_IDS,
        *PLATFORM_TOOL_IDS,
        *PLATFORM_INTENT_IDS,
        *PLATFORM_EXPERIENCE_IDS,
    )
)


def canonical_core_topic_skill_id(item: dict[str, Any]) -> str:
    """Resolve only exact institution-named copies of the three core methods."""

    if str(item.get("category") or "") != "主题":
        return ""
    base_skill_id = str(item.get("baseSkillId") or "").strip()
    if base_skill_id in CORE_TOPIC_SKILL_IDS:
        return base_skill_id
    item_id = str(item.get("id") or "").strip()
    if item_id in CORE_TOPIC_SKILL_IDS:
        return item_id
    kind_by_suffix = {
        "descriptive": "topic-descriptive",
        "attribution": "topic-attribution",
        "predictive": "topic-predictive",
    }
    if item_id.startswith("institution."):
        matched = kind_by_suffix.get(item_id.rsplit(".", 1)[-1])
        if matched:
            return matched
    name = str(item.get("name") or "").strip()
    for skill_id, label in CORE_TOPIC_SKILL_LABELS.items():
        if name == label or any(name == f"{institution}{label}" for institution in OPERATING_TENANTS):
            return skill_id
    return ""

SYSTEM_MANAGED_ASSET_IDS = {
    ("topic_table", "topic_core_weekly_metrics"),
    *(("analysis_skill", skill_id) for skill_id in PLATFORM_ANALYSIS_SKILL_IDS),
}

def _platform_scene_skill(
    skill_id: str,
    name: str,
    description: str,
    method: str,
    output_format: str,
    viewpoint: str,
    sort_order: int,
) -> dict[str, Any]:
    return {
        "id": skill_id,
        "name": name,
        "category": "场景",
        "description": description,
        "memoryRefs": [],
        "toolRefs": [],
        "analysisMethod": method,
        "documentAbstraction": "提取当前页面范围、选中图表、文本框光标、语音原文、已选数据表和用户问题。",
        "outputFormat": output_format,
        "viewpointStrategy": viewpoint,
        "recommendedSkillIds": list(CORE_TOPIC_SKILL_IDS),
        "enabled": True,
        "displayLocation": "intelligent_analysis",
        "sortOrder": sort_order,
        "systemManaged": True,
        "deletable": False,
    }


SCENE_INTENT_SKILL = _platform_scene_skill(
    SCENE_INTENT_SKILL_ID,
    "场景分析判断",
    "数据分析意图识别：先判断发生在图表追问、整页 AI 分析、文本框实时语音还是智能分析主查询，再规划描述、归因、预测等主题 Skill。",
    "先识别分析位置和语音意图（图表操控 / 文本转写 / AI 栏语音提问），再识别描述、归因、预测，并可组合多个主题 Skill。",
    "场景 / 语音意图 / 分析方法 / 调度 Skill / 数据范围",
    "先定位场景再分析；记录不分析；分析不编造；多 Skill 只组合被问题命中的能力。",
    1,
)
SCENE_CHART_FOLLOWUP_SKILL = _platform_scene_skill(
    SCENE_CHART_FOLLOWUP_SKILL_ID,
    "图表追问分析",
    "可视化图表点击追问后，右边栏 AI 分析只针对该图绑定的单个数据集。支持语音或文本提问。",
    "只使用当前图表绑定数据。识别描述、归因或预测后输出短结论和聚焦图，不汇总整页其他图表。",
    "短结论 / 聚焦图 / 数据范围 / 分析方法",
    "结论必须落在当前图的指标、维度和返回行上。",
    2,
)
SCENE_PAGE_RAIL_SKILL = _platform_scene_skill(
    SCENE_PAGE_RAIL_SKILL_ID,
    "整页AI分析",
    "未选中单个可视化时，右边栏 AI 分析汇总当前页全部可视化数据。",
    "收集当前页各图已查询数据后，按描述、归因或预测形成整页结论，避免只分析一张图。",
    "整页结论 / 主要图表证据 / 跨图对比 / 分析方法",
    "没有选中单图时必须声明结论来自整页数据。",
    3,
)
SCENE_TEXTBOX_VOICE_SKILL = _platform_scene_skill(
    SCENE_TEXTBOX_VOICE_SKILL_ID,
    "文本框实时语音",
    "可视化文本框点击实时语音后，只将语音转成文字写入光标所在的标题或正文，不触发数据分析。",
    "持续接收语音转写，停顿一秒结束当前段落；只写入文字，不进入文本推理运行时。",
    "写入位置 / 转写原文",
    "即使口述中出现分析、原因或预测等词，也只按原文转写。",
    4,
)
SCENE_SELF_ANALYSIS_SKILL = _platform_scene_skill(
    SCENE_SELF_ANALYSIS_SKILL_ID,
    "智能分析主查询",
    "智能分析页基于当前所选数据表做完整分析，不锚定单张可视化。",
    "使用用户已选数据表，按描述、归因或预测组织查询、可视化和结论。",
    "分析结论 / 数据证据 / 可视化 / 后续动作",
    "未选数据表时不得改用其他机构或默认样本表。",
    5,
)
PLATFORM_SCENE_SKILLS = (
    SCENE_INTENT_SKILL,
    SCENE_CHART_FOLLOWUP_SKILL,
    SCENE_PAGE_RAIL_SKILL,
    SCENE_TEXTBOX_VOICE_SKILL,
    SCENE_SELF_ANALYSIS_SKILL,
)

# Historical demonstration assets are deliberately identified by stable IDs,
# never by a broad tenant or title match. They must not reappear when a real
# tenant starts with an empty production catalog.
RETIRED_SAMPLE_ASSET_IDS = frozenset({
    ("raw_table", "raw_loan_operation_fact"),
    ("raw_table", "raw_mock_institution_100"),
    ("raw_table", "raw_mock_customer_100"),
    ("raw_table", "raw_mock_loan_order_100"),
    ("topic_table", "topic_core_weekly_metrics"),
    ("topic_table", "topic_weekly_branch_rank"),
    ("topic_table", "topic_m1_overdue_diagnosis"),
    ("topic_table", "topic_channel_roi"),
    ("topic_table", "topic_customer_conversion"),
    ("topic_table", "topic_mock_institution_operation"),
    ("topic_table", "topic_mock_customer_profile"),
    ("topic_table", "topic_mock_loan_funnel"),
    ("intent", "intent_branch_rank"),
    ("intent", "intent_risk_diagnosis"),
    ("analysis_experience", "exp_weekly_growth_quality"),
    ("analysis_experience", "exp_m1_risk_check"),
    ("knowledge_file", "kf_consumer_loan_playbook"),
    ("knowledge_file", "kf_weekly_report_memory"),
    ("analysis_shortcut", "shortcut-branch-ranking"),
    ("analysis_shortcut", "shortcut-m1-attribution"),
    ("analysis_shortcut", "shortcut-channel-roi"),
    ("analysis_shortcut", "shortcut-customer-conversion"),
    ("analysis_shortcut", "shortcut-institution-operation"),
    ("analysis_shortcut", "shortcut-customer-profile"),
    ("analysis_shortcut", "shortcut-loan-funnel"),
})

TENANT_MAINTAINED_ASSET_TYPES = frozenset({
    "analysis_skill",
    "external_tool",
    "analysis_shortcut",
    "intent",
    "analysis_experience",
    "knowledge_file",
    "user_behavior_habit",
    "conclusion_rule",
})
SYSTEM_CATALOG_AUTHORS = frozenset({"system", "development_seed"})


def _tenant_display_label(tenant_id: str) -> str:
    return str(tenant_id or "").removeprefix("tenant:").strip()


def _catalog_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("id", "name", "title", "description", "provider", "endpoint", "query", "owner")
    )


def _institution_aliases(label: str) -> tuple[str, ...]:
    label = str(label or "").strip()
    if not label:
        return ()
    aliases = [label]
    for suffix in ("银行", "消金"):
        if label.endswith(suffix) and len(label) > len(suffix) + 1:
            aliases.append(label[: -len(suffix)])
    return tuple(aliases)


def _mentions_other_institution(item: dict[str, Any], tenant_id: str) -> bool:
    current = _tenant_display_label(tenant_id)
    blob = _catalog_text(item)
    current_aliases = set(_institution_aliases(current))
    for label in OPERATING_TENANTS:
        if not label or label == current:
            continue
        if any(alias and alias not in current_aliases and alias in blob for alias in _institution_aliases(label)):
            return True
    return False


def _is_cloned_system_catalog_item(item_type: str, item: dict[str, Any]) -> bool:
    if str(item.get("updatedBy") or item.get("updated_by") or "") not in SYSTEM_CATALOG_AUTHORS:
        return False
    item_id = str(item.get("id") or "")
    return any(str(row.get("id") or "") == item_id for row in DEFAULT_ASSET_ITEMS.get(item_type, []))


def visible_items_for_tenant(tenant_id: str, item_type: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hide cloned system catalogs and other institutions' named tools/skills."""

    if item_type not in TENANT_MAINTAINED_ASSET_TYPES:
        return items
    keep_system_defaults = tenant_id in {"tenant_demo"} or _tenant_display_label(tenant_id) in {"演示机构"}
    visible: list[dict[str, Any]] = []
    for item in items:
        if _mentions_other_institution(item, tenant_id):
            continue
        if (
            not keep_system_defaults
            and _is_cloned_system_catalog_item(item_type, item)
            and str(item.get("id") or "") not in PLATFORM_VISIBLE_CATALOG_IDS
        ):
            continue
        visible.append(item)
    return visible


def catalog_item_template(item_type: str, item_id: str) -> dict[str, Any] | None:
    wanted = str(item_id or "").strip()
    if not wanted:
        return None
    if item_type == "analysis_skill":
        return analysis_skill_template(wanted)
    for item in DEFAULT_ASSET_ITEMS.get(item_type, []):
        if str(item.get("id") or "") == wanted:
            return deepcopy(item)
    return None


def seed_platform_capability_catalog(store: Any, tenant_id: str, updated_by: str) -> None:
    """Idempotently place the governed 双周报 Skill/tool/memory catalog on one tenant."""

    catalog = (
        ("analysis_skill", PLATFORM_ANALYSIS_SKILL_IDS),
        ("external_tool", PLATFORM_TOOL_IDS),
        ("intent", PLATFORM_INTENT_IDS),
        ("analysis_experience", PLATFORM_EXPERIENCE_IDS),
    )
    for item_type, item_ids in catalog:
        for item_id in item_ids:
            template = catalog_item_template(item_type, item_id)
            if template is None:
                continue
            existing = store.get_item(tenant_id, item_type, item_id)
            if existing is not None and str(existing.get("lifecycleStatus") or "") == "active":
                continue
            store.upsert_item(
                tenant_id,
                item_type,
                {**(existing or {}), **template, "id": item_id},
                updated_by=updated_by,
                lifecycle_status="active",
            )


def analysis_skill_template(skill_id: str) -> dict[str, Any] | None:
    wanted = str(skill_id or "").strip()
    if not wanted:
        return None
    for item in PLATFORM_SCENE_SKILLS:
        if str(item.get("id") or "") == wanted:
            return deepcopy(item)
    for item in DEFAULT_ASSET_ITEMS.get("analysis_skill", []):
        if str(item.get("id") or "") == wanted:
            return deepcopy(item)
    return None


def _runtime_default_items(item_type: str) -> list[dict[str, Any]]:
    return [
        item
        for item in DEFAULT_ASSET_ITEMS.get(item_type, [])
        if (item_type, str(item.get("id") or "")) not in RETIRED_SAMPLE_ASSET_IDS
    ]


def _require_deletable_asset(item_type: str, item_id: str) -> None:
    if (str(item_type), str(item_id)) in SYSTEM_MANAGED_ASSET_IDS:
        raise PermissionError("system_managed_data_asset_cannot_be_deleted")


DEFAULT_ASSET_ITEMS: dict[str, list[dict[str, Any]]] = {
    "raw_table": [
        {
            "id": "raw_loan_operation_fact",
            "tableNameEn": "loan_operation_fact",
            "tableNameCn": "信贷经营明细表",
            "source": "QBI",
            "tableType": "bottom",
            "primaryKey": "loan_id",
            "dateField": "stat_date",
            "orgField": "branch_name",
            "customerField": "customer_id",
            "description": "消费贷、经营贷的放款、余额、动支和风险明细。",
            "updateFrequency": "T+1",
            "restrictions": "仅返回当前机构和授权产品线。",
            "exampleSql": "select branch_name, sum(loan_amount) from loan_operation_fact where tenant_id = :tenant_id group by branch_name",
            "fields": [
                {
                    "fieldNameEn": "loan_amount",
                    "fieldNameCn": "放款金额",
                    "type": "decimal",
                    "explanation": "实际发放本金金额，单位元。",
                    "isMetric": True,
                    "metricLogic": "sum(loan_amount)",
                    "exampleUsage": "机构放款金额排名、周净增拆解",
                },
                {
                    "fieldNameEn": "m1_overdue_rate",
                    "fieldNameCn": "M1逾期率",
                    "type": "decimal",
                    "explanation": "M1逾期贷款余额 / 贷款余额。",
                    "isMetric": True,
                    "metricLogic": "sum(m1_balance) / nullif(sum(balance), 0)",
                    "exampleUsage": "风险异动和增长质量校验",
                },
            ],
            "updatedAt": "2026-07-05",
        },
        *MOCK_RAW_TABLES,
    ],
    "topic_table": [
        {
            "id": "topic_core_weekly_metrics",
            "name": "经营周报三指标",
            "code": "core_weekly_metrics",
            "description": "经营周报固定使用的在贷余额、放款金额和新增余额周度趋势表。",
            "systemManaged": True,
            "deletable": False,
            "datasetId": "weekly_core_metrics_mart",
            "metricCodes": ["loan_balance", "loan_amount", "new_balance"],
            "defaultMetrics": ["loan_balance", "loan_amount", "new_balance"],
            "dimensionCodes": ["stat_week"],
            "defaultDimensions": ["stat_week"],
            "chartTypes": ["column", "line", "table"],
            "analysisAngles": ["周度趋势", "规模变化", "新增贡献"],
            "sql": "select stat_week, sum(loan_balance) as loan_balance, sum(loan_amount) as loan_amount, sum(new_balance) as new_balance from weekly_core_metrics_fact where tenant_id = :tenant_id group by stat_week order by stat_week",
            "fields": [
                {"fieldNameEn": "stat_week", "fieldNameCn": "日期", "type": "string", "explanation": "周度统计周期。"},
                {"fieldNameEn": "loan_balance", "fieldNameCn": "在贷余额", "type": "decimal", "explanation": "统计期末剩余未还本金。", "isMetric": True, "metricCode": "loan_balance"},
                {"fieldNameEn": "loan_amount", "fieldNameCn": "放款金额", "type": "decimal", "explanation": "统计周期实际发放本金。", "isMetric": True, "metricCode": "loan_amount"},
                {"fieldNameEn": "new_balance", "fieldNameCn": "新增余额", "type": "decimal", "explanation": "统计周期新增贷款余额。", "isMetric": True, "metricCode": "new_balance"},
            ],
            "fieldExplanations": "日期、在贷余额、放款金额和新增余额。",
            "applicableScene": "经营周报三指标",
            "relatedIntent": "经营分析 / 核心指标",
            "relatedExperience": "exp_weekly_growth_quality",
            "quickDisplay": False,
            "reportReference": "经营周报-核心指标表现记录",
            "source": "manual",
            "updatedAt": "2026-07-16",
        },
        {
            "id": "topic_weekly_branch_rank",
            "name": "分行放款排名分析",
            "code": "weekly_branch_loan_rank",
            "description": "复用机构周报和智能分析的分行放款规模、转化、风险组合视图。",
            "datasetId": "loan_operation_mart",
            "metricCodes": ["loan_amount"],
            "sql": "select branch_name, product_line, sum(loan_amount) as loan_amount from loan_operation_fact where tenant_id = :tenant_id group by branch_name, product_line order by loan_amount desc limit 20",
            "fields": [
                {
                    "fieldNameEn": "branch_name",
                    "fieldNameCn": "机构名称",
                    "type": "string",
                    "explanation": "来自原始表的分支机构名称，用于机构维度排名。",
                    "exampleUsage": "分行放款排名、机构贡献拆解",
                },
                {
                    "fieldNameEn": "product_line",
                    "fieldNameCn": "产品线",
                    "type": "string",
                    "explanation": "消费贷、经营贷或综合授信产品分类。",
                    "exampleUsage": "产品线对比、业务结构分析",
                },
                {
                    "fieldNameEn": "loan_amount",
                    "fieldNameCn": "放款金额",
                    "type": "decimal",
                    "explanation": "按机构和产品线聚合后的放款金额。",
                    "exampleUsage": "排名、目标达成、经营周报",
                },
                {
                    "fieldNameEn": "conversion_rate",
                    "fieldNameCn": "转化率",
                    "type": "decimal",
                    "explanation": "进件到有效授信或动支的转化效率。",
                    "exampleUsage": "增长质量、漏斗分析",
                },
                {
                    "fieldNameEn": "m1_overdue_rate",
                    "fieldNameCn": "M1逾期率",
                    "type": "decimal",
                    "explanation": "M1逾期余额占贷款余额比例。",
                    "exampleUsage": "风险校验、异常预警",
                },
            ],
            "fieldExplanations": "机构、产品线、放款金额、转化率、M1逾期率。",
            "applicableScene": "经营周报、机构督导、自助分析",
            "relatedIntent": "经营分析 / 机构排名",
            "relatedExperience": "exp_weekly_growth_quality",
            "quickDisplay": True,
            "reportReference": "经营周报-业绩与业务波动",
            "source": "manual",
            "updatedAt": "2026-07-05",
        },
        {
            "id": "topic_m1_overdue_diagnosis",
            "name": "M1逾期率归因分析",
            "code": "m1_overdue_diagnosis",
            "description": "按产品、客群、机构拆解 M1 异动，并给出风险提示。",
            "datasetId": "risk_operation_mart",
            "metricCodes": ["m1_overdue_rate"],
            "sql": "select branch_name, product_line, customer_segment, avg(m1_overdue_rate) as m1_overdue_rate from loan_operation_fact where tenant_id = :tenant_id group by branch_name, product_line, customer_segment",
            "fields": [
                {
                    "fieldNameEn": "branch_name",
                    "fieldNameCn": "机构名称",
                    "type": "string",
                    "explanation": "来自原始表的分支机构名称。",
                    "exampleUsage": "定位高风险机构",
                },
                {
                    "fieldNameEn": "product_line",
                    "fieldNameCn": "产品线",
                    "type": "string",
                    "explanation": "消费贷、经营贷或综合授信产品分类。",
                    "exampleUsage": "产品线风险对比",
                },
                {
                    "fieldNameEn": "customer_segment",
                    "fieldNameCn": "客群",
                    "type": "string",
                    "explanation": "客户所属经营或消费客群标签。",
                    "exampleUsage": "客群风险归因",
                },
                {
                    "fieldNameEn": "m1_overdue_rate",
                    "fieldNameCn": "M1逾期率",
                    "type": "decimal",
                    "explanation": "按机构、产品线和客群聚合后的平均 M1 逾期率。",
                    "exampleUsage": "逾期异动解释、风险策略调整",
                },
            ],
            "fieldExplanations": "机构、产品线、客群、M1逾期率。",
            "applicableScene": "风险分析、周报异常解释",
            "relatedIntent": "风险分析 / 逾期归因",
            "relatedExperience": "exp_m1_risk_check",
            "quickDisplay": True,
            "reportReference": "经营周报-风险提示",
            "source": "manual",
            "updatedAt": "2026-07-05",
        },
        {
            "id": "topic_channel_roi",
            "name": "渠道获客成本与ROI分析",
            "code": "channel_operation_mart",
            "description": "按渠道、月份、产品线和机构比较获客成本、营销投入与归因收入。",
            "datasetId": "channel_operation_mart",
            "metricCodes": ["customer_acquisition_cost", "roi"],
            "defaultMetrics": ["customer_acquisition_cost", "roi"],
            "dimensionCodes": ["channel", "month", "product_line", "branch_name"],
            "defaultDimensions": ["channel", "month"],
            "sql": "select channel, month, product_line, branch_name, customer_acquisition_cost, roi from channel_operation_mart where tenant_id = :tenant_id",
            "fields": [
                {"fieldNameEn": "channel", "fieldNameCn": "渠道", "type": "string", "explanation": "客户触达或获客渠道。"},
                {"fieldNameEn": "month", "fieldNameCn": "月份", "type": "string", "explanation": "自然月。"},
                {"fieldNameEn": "customer_acquisition_cost", "fieldNameCn": "获客成本", "type": "decimal", "explanation": "营销成本除以新增客户数。", "isMetric": True, "metricCode": "customer_acquisition_cost"},
                {"fieldNameEn": "roi", "fieldNameCn": "投入产出比", "type": "decimal", "explanation": "归因收入除以营销成本。", "isMetric": True, "metricCode": "roi"},
            ],
            "fieldExplanations": "渠道、月份、产品线、机构、获客成本和ROI。",
            "applicableScene": "渠道经营、营销复盘、智能分析",
            "relatedIntent": "经营分析 / 渠道ROI",
            "relatedExperience": "exp_weekly_growth_quality",
            "quickDisplay": True,
            "reportReference": "经营周报-渠道效率",
            "source": "mock_json",
            "updatedAt": "2026-07-12",
        },
        {
            "id": "topic_customer_conversion",
            "name": "客群转化与活跃分析",
            "code": "customer_operation_mart",
            "description": "按客群、产品线和机构比较转化率与活跃客户规模。",
            "datasetId": "customer_operation_mart",
            "metricCodes": ["conversion_rate", "active_customer_count"],
            "defaultMetrics": ["conversion_rate", "active_customer_count"],
            "dimensionCodes": ["customer_segment", "product_line", "branch_name", "month"],
            "defaultDimensions": ["customer_segment", "product_line"],
            "sql": "select customer_segment, product_line, branch_name, month, conversion_rate, active_customer_count from customer_operation_mart where tenant_id = :tenant_id",
            "fields": [
                {"fieldNameEn": "customer_segment", "fieldNameCn": "客群", "type": "string", "explanation": "客户经营分群。"},
                {"fieldNameEn": "product_line", "fieldNameCn": "产品线", "type": "string", "explanation": "消费贷、经营贷或综合授信。"},
                {"fieldNameEn": "conversion_rate", "fieldNameCn": "转化率", "type": "decimal", "explanation": "转化客户数除以可经营客户数。", "isMetric": True, "metricCode": "conversion_rate"},
                {"fieldNameEn": "active_customer_count", "fieldNameCn": "活跃客户数", "type": "integer", "explanation": "统计期内活跃客户数量。", "isMetric": True, "metricCode": "active_customer_count"},
            ],
            "fieldExplanations": "客群、产品线、机构、月份、转化率和活跃客户数。",
            "applicableScene": "客群经营、产品运营、智能分析",
            "relatedIntent": "经营分析 / 客群转化",
            "relatedExperience": "exp_weekly_growth_quality",
            "quickDisplay": True,
            "reportReference": "经营周报-客群经营",
            "source": "mock_json",
            "updatedAt": "2026-07-12",
        },
        *MOCK_TOPIC_TABLES,
    ],
    "intent": [
        {
            "id": "intent_branch_rank",
            "scenario": "经营分析",
            "purpose": "机构排名",
            "description": "识别放款、余额和转化表现分化，定位头部贡献和尾部拖累。",
            "keywords": "排名, TOP, 分行, 机构, 放款金额",
            "relatedTopic": "weekly_branch_loan_rank",
            "relatedMetrics": "放款金额, 转化率, 动支率",
            "relatedExperience": "exp_weekly_growth_quality",
            "pageScope": "智能分析, 经营周报",
            "enabled": True,
            "examples": "本月各分行放款金额排名TOP10",
        },
        {
            "id": "intent_risk_diagnosis",
            "scenario": "风险分析",
            "purpose": "逾期归因",
            "description": "分析 M1 逾期率变化和产品、客群、机构结构的关系。",
            "keywords": "M1, 逾期, 风险, 上升, 原因",
            "relatedTopic": "m1_overdue_diagnosis",
            "relatedMetrics": "M1逾期率, 余额, 风险迁徙率",
            "relatedExperience": "exp_m1_risk_check",
            "pageScope": "智能分析, 经营周报",
            "enabled": True,
            "examples": "M1逾期率上升原因归因",
        },
    ],
    "analysis_experience": [
        {
            "id": "exp_weekly_growth_quality",
            "name": "周报增长质量分析经验",
            "relatedTopic": "weekly_branch_loan_rank",
            "relatedIntent": "经营分析 / 机构排名",
            "steps": "先看规模排名，再看转化、动支和逾期，最后落到机构行动。",
            "metrics": "放款金额, 周净增, 转化率, 动支率, M1逾期率",
            "rules": "规模增长必须同步校验风险和转化；尾部机构需拆到客户经理。",
            "commonConclusions": "头部机构贡献稳定；尾部机构多由进件不足或动支节奏偏慢拖累。",
            "riskTips": "若 M1 同步上升，不建议仅按规模增长评价。",
            "summaryTemplate": "核心结论 / 主要异常 / 关键原因 / 数据证据 / 经营建议 / 风险提示 / 后续跟进动作",
            "institutionScope": "全部机构",
            "enabled": True,
            "updatedAt": "2026-07-05",
        },
        {
            "id": "exp_m1_risk_check",
            "name": "M1风险异动校验经验",
            "relatedTopic": "m1_overdue_diagnosis",
            "relatedIntent": "风险分析 / 逾期归因",
            "steps": "按机构、产品、客群三层拆分，结合新增客户和存量续贷解释。",
            "metrics": "M1逾期率, 贷款余额, 新增客户数, 风险迁徙率",
            "rules": "单一维度异常必须二次交叉验证；样本量过小时只做风险提示。",
            "commonConclusions": "逾期抬升通常来自尾部机构、经营贷客群或存量客户续贷压力。",
            "riskTips": "关注高风险客群叠加高动支机构。",
            "summaryTemplate": "核心结论 / 主要异常 / 关键原因 / 数据证据 / 经营建议 / 风险提示 / 后续跟进动作",
            "institutionScope": "全部机构",
            "enabled": True,
            "updatedAt": "2026-07-05",
        },
    ],
    "knowledge_file": [
        {
            "id": "kf_consumer_loan_playbook",
            "title": "消费贷客群经营手册",
            "coverage": "已启用",
            "items": 38,
            "updated": "今天 09:20",
            "owner": "数据运营",
            "tags": "消费贷, 客群, 转化",
        },
        {
            "id": "kf_weekly_report_memory",
            "title": "周报分析口径记忆",
            "coverage": "待复核",
            "items": 18,
            "updated": "2天前",
            "owner": "经营分析",
            "tags": "周报, 口径, 经验",
        },
    ],
    "user_behavior_habit": [],
    "analysis_skill": [
        *[deepcopy(item) for item in PLATFORM_SCENE_SKILLS],
        {
            "id": "scene-weekly-report", "name": "周报分析", "category": "场景",
            "description": "围绕机构经营周报组织口径、证据、观点和行动建议。",
            "memoryRefs": ["intent_branch_rank", "exp_weekly_growth_quality"],
            "toolRefs": ["tool-financial-analyst", "tool-teams-cloud-doc"],
            "analysisMethod": "先核对报告周期和指标口径，再按规模、转化、风险和机构贡献形成证据链。",
            "documentAbstraction": "提取上传文档中的报告周期、经营指标、机构观点、异常说明和待办动作。",
            "outputFormat": "核心结论 / 主要异常 / 数据证据 / 经营建议 / 风险提示 / 后续动作",
            "viewpointStrategy": "规模增长必须同步校验转化与风险，不以单一排名代替经营判断。",
            "recommendedSkillIds": ["topic-descriptive", "topic-attribution", "topic-financial-budget"],
            "enabled": True, "sortOrder": 10,
        },
        {
            "id": "scene-daily-operation", "name": "运营日常分析", "category": "场景",
            "description": "面向日常经营监控、机构对比和异常跟进的快速分析。",
            "memoryRefs": ["intent_branch_rank", "exp_weekly_growth_quality"],
            "toolRefs": ["tool-outlook", "tool-teams-t5t"],
            "analysisMethod": "先定位变化，再拆机构、产品、客群和渠道，最后生成可执行跟进项。",
            "documentAbstraction": "识别文件中的业务目标、日报字段、机构名单、异常阈值和责任人。",
            "outputFormat": "指标表现 / 异常定位 / 原因拆解 / 行动清单",
            "viewpointStrategy": "优先输出有证据、可跟进、能落到机构和责任人的观点。",
            "recommendedSkillIds": ["topic-descriptive", "topic-attribution", "topic-exploratory"],
            "enabled": True, "sortOrder": 20,
        },
        {
            "id": "scene-risk-strategy", "name": "风险策略分析", "category": "场景",
            "description": "围绕信贷、逾期、可疑交易和流动性风险形成策略判断。",
            "memoryRefs": ["exp_m1_risk_check"],
            "toolRefs": ["tool-confluence-search", "tool-financial-analyst"],
            "analysisMethod": "按风险事件、暴露规模、迁徙路径、反证和策略影响逐层校验。",
            "documentAbstraction": "提取策略版本、客群边界、阈值、例外条件和历史验证结论。",
            "outputFormat": "风险结论 / 证据与反证 / 策略影响 / 建议动作 / 监控指标",
            "viewpointStrategy": "结论必须同时呈现证据、反证、适用边界和潜在误伤。",
            "recommendedSkillIds": ["topic-credit-risk", "topic-suspicious-transaction", "topic-overdue-risk"],
            "enabled": True, "sortOrder": 30,
        },
        *[
            {
                "id": skill_id, "name": name, "category": "主题", "description": description,
                "memoryRefs": memory_refs, "toolRefs": tool_refs, "analysisMethod": method,
                "documentAbstraction": "按业务对象、时间范围、指标口径、限制条件和证据片段抽取输入文档。",
                "outputFormat": output_format, "viewpointStrategy": viewpoint, "recommendedSkillIds": [],
                "enabled": True, "displayLocation": "intelligent_analysis", "sortOrder": 100 + index * 10,
            }
            for index, (skill_id, name, description, memory_refs, tool_refs, method, output_format, viewpoint) in enumerate([
                ("topic-descriptive", "描述性分析", "描述现状、结构、分布和变化。", ["exp_weekly_growth_quality"], [], "核对总量后做分组、趋势、极值、零值和异常值描述。", "总体 / 结构 / 趋势 / 异常 / 口径", "区分事实描述和解释性判断。"),
                ("topic-attribution", "归因分析", "拆解指标变化的机构、产品、客群和渠道贡献。", ["exp_weekly_growth_quality"], ["tool-financial-analyst"], "建立对比基线，计算贡献度，校验交叉维度和反事实。", "变化 / 贡献拆解 / 原因证据 / 反证 / 动作", "不把相关性直接表述为因果。"),
                ("topic-predictive", "预测分析", "基于历史序列给出预测区间和关键假设。", [], ["tool-financial-analyst"], "检查时间序列质量，建立基线模型，输出区间并做敏感性分析。", "预测值 / 区间 / 假设 / 误差 / 监控", "预测必须附带不确定性和失效条件。"),
                ("topic-exploratory", "探索性分析", "发现数据中的结构、关联、异常和后续问题。", [], [], "从分布、相关、聚类和异常切入，形成可验证的后续假设。", "发现 / 假设 / 证据 / 下一步验证", "将发现表述为待验证假设。"),
                ("topic-financial-budget", "财务预算分析", "对比预算、实际、预测和资源投入效率。", [], ["tool-financial-analyst"], "核对预算版本，计算差异和达成率，拆解量价与结构影响。", "预算 / 实际 / 差异 / 原因 / 滚动预测", "同时关注达成、投入效率和可持续性。"),
                ("topic-credit-risk", "信用风险分析", "分析信用风险暴露、迁徙和策略影响。", ["exp_m1_risk_check"], [], "按客群、产品、机构和账龄拆解风险指标并校验样本量。", "风险水平 / 迁徙 / 证据 / 策略建议", "避免用小样本异常泛化整体风险。"),
                ("topic-suspicious-transaction", "可疑交易分析", "识别交易模式、关联关系和可疑证据链。", [], ["tool-confluence-search"], "从规则命中、行为偏离、关系网络和历史事件交叉验证。", "风险事件 / 模式 / 关联证据 / 处置建议", "保留正常业务解释和反证。"),
                ("topic-liquidity-risk", "流动性风险分析", "评估期限错配、资金缺口和压力情景。", [], ["tool-financial-analyst"], "计算期限缺口、集中度和压力情景下的覆盖能力。", "缺口 / 情景 / 覆盖 / 风险缓释", "明确情景假设，不将压力结果当成实际预测。"),
                ("topic-overdue-risk", "逾期风险分析", "拆解逾期率、余额、迁徙和催收表现。", ["exp_m1_risk_check"], [], "先核对分子分母，再按账龄、客群、机构和产品拆解。", "逾期表现 / 迁徙 / 原因 / 风险名单 / 动作", "逾期率与余额规模必须同时判断。"),
            ])
        ],
    ],
    "external_tool": [
        {"id": "tool-confluence-search", "name": "Confluence知识检索", "provider": "Confluence", "toolType": "knowledge_search", "description": "检索企业知识库、制度和项目文档。", "endpoint": "", "capabilities": ["知识检索", "文档引用"], "enabled": False, "status": "未配置"},
        {"id": "tool-outlook", "name": "Outlook邮箱调用", "provider": "Microsoft Graph", "toolType": "email", "description": "查询邮件、生成草稿并在授权后发送。", "endpoint": "", "capabilities": ["邮件检索", "草稿生成", "授权发送"], "enabled": False, "status": "未配置"},
        {"id": "tool-teams-cloud-doc", "name": "Teams-云文档工具", "provider": "Microsoft Teams", "toolType": "document", "description": "读取和更新 Teams 关联云文档。", "endpoint": "", "capabilities": ["云文档读取", "文档更新"], "enabled": False, "status": "未配置"},
        {"id": "tool-teams-t5t", "name": "Teams-T5T工具", "provider": "Microsoft Teams", "toolType": "collaboration", "description": "把分析结论转成团队协同任务。", "endpoint": "", "capabilities": ["团队消息", "任务协同"], "enabled": False, "status": "未配置"},
        {"id": "tool-financial-analyst", "name": "财务分析师", "provider": "Internal Agent", "toolType": "agent", "description": "调用受治理的财务分析智能体。", "endpoint": "", "capabilities": ["预算分析", "财务诊断", "报告生成"], "enabled": True, "status": "已接入"},
    ],
    "analysis_shortcut": [
        {"id": "shortcut-branch-ranking", "title": "分行放款排名分析", "query": "2026年7月各分行放款金额排名TOP10，并比较产品线动支率", "skillIds": ["scene-daily-operation", "topic-descriptive"], "tableIds": ["topic_weekly_branch_rank"], "memoryIds": [], "visible": True, "sortOrder": 10, "ownerUserId": ""},
        {"id": "shortcut-m1-attribution", "title": "M1逾期率归因分析", "query": "消费贷和经营贷的M1逾期率变化及原因", "skillIds": ["scene-risk-strategy", "topic-attribution"], "tableIds": ["topic_m1_overdue_diagnosis"], "memoryIds": [], "visible": True, "sortOrder": 20, "ownerUserId": ""},
        {"id": "shortcut-channel-roi", "title": "渠道获客成本与ROI分析", "query": "按渠道和月份比较获客成本与ROI，定位高投入低产出渠道", "skillIds": ["scene-daily-operation", "topic-attribution"], "tableIds": ["topic_channel_roi"], "memoryIds": [], "visible": True, "sortOrder": 30, "ownerUserId": ""},
        {"id": "shortcut-customer-conversion", "title": "客群转化与活跃分析", "query": "按客群和产品线比较转化率与活跃客户数，识别优先经营客群", "skillIds": ["scene-daily-operation", "topic-descriptive"], "tableIds": ["topic_customer_conversion"], "memoryIds": [], "visible": True, "sortOrder": 40, "ownerUserId": ""},
        {"id": "shortcut-institution-operation", "title": "机构经营规模与目标分析", "query": "按分行和机构层级分析机构数、员工人数、客户经理人数、授信目标金额和动支目标金额", "skillIds": ["scene-weekly-report", "topic-financial-budget"], "tableIds": ["topic_mock_institution_operation"], "memoryIds": [], "visible": True, "sortOrder": 50, "ownerUserId": ""},
        {"id": "shortcut-customer-profile", "title": "客户画像与风险分层分析", "query": "按客群、行业和风险等级分析客户数、活跃客户数、授信客户数、动支客户数和贷款余额", "skillIds": ["scene-risk-strategy", "topic-credit-risk"], "tableIds": ["topic_mock_customer_profile"], "memoryIds": [], "visible": True, "sortOrder": 60, "ownerUserId": ""},
        {"id": "shortcut-loan-funnel", "title": "贷款申请授信动支漏斗分析", "query": "按分行和产品线分析完件笔数、授信通过率、动支率、授信金额和动支金额", "skillIds": ["scene-daily-operation", "topic-descriptive"], "tableIds": ["topic_mock_loan_funnel"], "memoryIds": [], "visible": True, "sortOrder": 70, "ownerUserId": ""},
    ],
}


class InMemoryDataAssetStore:
    def __init__(self, seed_defaults: bool = True) -> None:
        self._items_by_tenant_type: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self._versions: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._reviews: list[dict[str, Any]] = []
        self._raw_table_external_references: dict[tuple[str, str], dict[str, Any]] = {}
        if seed_defaults:
            self.seed_defaults("tenant_demo")

    def list_bundle(self, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
        return {output_key: self._list(tenant_id, item_type) for item_type, output_key in ASSET_BUNDLE_KEYS.items()}

    def list_published_bundle(self, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
        return {output_key: self._list_published(tenant_id, item_type) for item_type, output_key in ASSET_BUNDLE_KEYS.items()}

    def list_raw_table_external_references(self, tenant_id: str) -> dict[str, dict[str, Any]]:
        return {
            source_key: dict(record)
            for (record_tenant, source_key), record in self._raw_table_external_references.items()
            if record_tenant == tenant_id
        }

    def set_raw_table_external_reference(
        self, tenant_id: str, source_key: str, mode: str, schema_fingerprint: str, updated_by: str,
    ) -> dict[str, Any]:
        record = _raw_table_external_reference_record(source_key, mode, schema_fingerprint, updated_by)
        self._raw_table_external_references[(tenant_id, source_key)] = record
        return dict(record)

    def seed_defaults(self, tenant_id: str, updated_by: str = "development_seed") -> None:
        for item_type in DEFAULT_ASSET_ITEMS:
            for item in deepcopy(_runtime_default_items(item_type)):
                self.upsert_item(tenant_id, item_type, item, updated_by=updated_by, lifecycle_status="active")

    def seed_missing_defaults(self, tenant_id: str, updated_by: str = "development_seed") -> None:
        seed_platform_capability_catalog(self, tenant_id, updated_by)
        bundle = self.list_bundle(tenant_id)
        for item_type in DEFAULT_ASSET_ITEMS:
            # Tenant-maintained catalogs must not be re-cloned onto every
            # institution after an operator deletes or never created them.
            if item_type in TENANT_MAINTAINED_ASSET_TYPES:
                continue
            existing = {
                str(item.get("id") or ""): item
                for item in bundle.get(ASSET_BUNDLE_KEYS[item_type], [])
            }
            for item in deepcopy(_runtime_default_items(item_type)):
                item_id = str(item.get("id") or "")
                if item_id not in existing:
                    self.upsert_item(tenant_id, item_type, item, updated_by=updated_by, lifecycle_status="active")
                elif (
                    (item_type == "topic_table" and item_id == "topic_core_weekly_metrics")
                    or (item_type in {"topic_table", "analysis_shortcut"} and str(existing[item_id].get("updatedBy") or "") == "development_seed")
                ):
                    metadata_keys = (
                        (
                            "name", "description", "systemManaged", "deletable", "datasetId", "metricCodes",
                            "defaultMetrics", "dimensionCodes", "defaultDimensions", "chartTypes", "analysisAngles",
                            "sql", "fields", "fieldExplanations", "applicableScene", "reportReference",
                        )
                        if item_type == "topic_table"
                        else ("query", "skillIds", "tableIds", "visible", "sortOrder")
                    )
                    missing_metadata = {
                        key: item[key]
                        for key in metadata_keys
                        if key in item and existing[item_id].get(key) != item[key]
                    }
                    if missing_metadata:
                        self.upsert_item(
                            tenant_id,
                            item_type,
                            {**existing[item_id], **missing_metadata},
                            updated_by=updated_by,
                            lifecycle_status="active",
                        )

    def purge_retired_sample_assets(self, tenant_id: str) -> int:
        removed = 0
        for item_type, item_id in RETIRED_SAMPLE_ASSET_IDS:
            key = (tenant_id, item_type)
            if item_id in self._items_by_tenant_type.get(key, {}):
                del self._items_by_tenant_type[key][item_id]
                self._versions.pop((tenant_id, item_type, item_id), None)
                removed += 1
        return removed

    def upsert_item(
        self,
        tenant_id: str,
        item_type: str,
        item: dict[str, Any],
        updated_by: str | None = None,
        lifecycle_status: str | None = None,
    ) -> dict[str, Any]:
        fusion = prepare_asset_fusion(
            item_type,
            item,
            self._items_by_tenant_type.get((tenant_id, item_type), {}).values(),
        )
        normalized = _normalize_item(item_type, fusion.item, updated_by)
        _validate_asset_schema(item_type, normalized)
        status = _asset_status(lifecycle_status)
        key = (tenant_id, item_type, normalized["id"])
        versions = self._versions.setdefault(key, [])
        version_number = len(versions) + 1
        if status == "active":
            for version in versions:
                if version["lifecycleStatus"] == "active":
                    version["lifecycleStatus"] = "archived"
        governed = _governed_asset_payload(
            normalized,
            status=status,
            version_number=version_number,
            submitted_by=updated_by or "system",
            lock_version=version_number,
        )
        versions.append(deepcopy(governed))
        self._items_by_tenant_type.setdefault((tenant_id, item_type), {})[normalized["id"]] = governed
        for duplicate_id in fusion.duplicate_ids:
            duplicate_versions = self._versions.get((tenant_id, item_type, duplicate_id), [])
            if duplicate_versions:
                duplicate_versions[-1]["lifecycleStatus"] = "archived"
            self._items_by_tenant_type[(tenant_id, item_type)].pop(duplicate_id, None)
        return dict(governed)

    def get_item(self, tenant_id: str, item_type: str, item_id: str) -> dict[str, Any] | None:
        item = self._items_by_tenant_type.get((tenant_id, item_type), {}).get(item_id)
        return dict(item) if item else None

    def review_item(
        self,
        tenant_id: str,
        item_type: str,
        item_id: str,
        *,
        decision: str,
        reviewer_user_id: str,
        comments: str = "",
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        _require_review_decision(decision)
        key = (tenant_id, item_type, item_id)
        versions = self._versions.get(key, [])
        if not versions:
            raise KeyError("data_asset_not_found")
        candidate = versions[-1]
        if expected_version is not None and int(candidate["assetVersion"]) != int(expected_version):
            raise RuntimeError("data_asset_version_conflict")
        if candidate["lifecycleStatus"] not in {"draft", "review"}:
            raise RuntimeError("data_asset_not_reviewable")
        if candidate["submittedBy"] == reviewer_user_id:
            raise PermissionError("data_asset_four_eyes_required")
        next_status = "active" if decision == "approved" else "rejected"
        if next_status == "active":
            for version in versions[:-1]:
                if version["lifecycleStatus"] == "active":
                    version["lifecycleStatus"] = "archived"
        candidate.update(
            lifecycleStatus=next_status,
            reviewedBy=reviewer_user_id,
            reviewedAt=_utc_now(),
            reviewComment=str(comments or "")[:2000],
        )
        self._items_by_tenant_type[(tenant_id, item_type)][item_id] = deepcopy(candidate)
        self._reviews.append(
            {
                "reviewId": f"asset_review_{uuid4().hex}",
                "tenantId": tenant_id,
                "itemType": item_type,
                "itemId": item_id,
                "version": candidate["assetVersion"],
                "decision": decision,
                "reviewerUserId": reviewer_user_id,
                "comments": str(comments or "")[:2000],
                "createdAt": _utc_now(),
            }
        )
        return dict(candidate)

    def delete_item(self, tenant_id: str, item_type: str, item_id: str) -> bool:
        _require_valid_type(item_type)
        _require_deletable_asset(item_type, item_id)
        removed = self._items_by_tenant_type.setdefault((tenant_id, item_type), {}).pop(item_id, None)
        if removed is not None:
            for version in self._versions.get((tenant_id, item_type, item_id), []):
                if version.get("lifecycleStatus") in {"draft", "review", "active"}:
                    version["lifecycleStatus"] = "archived"
        return removed is not None

    def _list(self, tenant_id: str, item_type: str) -> list[dict[str, Any]]:
        items = self._items_by_tenant_type.get((tenant_id, item_type), {})
        return visible_items_for_tenant(
            tenant_id,
            item_type,
            sorted((_normalize_asset_payload_for_read(item_type, item) for item in items.values()), key=_sort_key),
        )

    def _list_published(self, tenant_id: str, item_type: str) -> list[dict[str, Any]]:
        published = []
        for (version_tenant, version_type, _), versions in self._versions.items():
            if version_tenant != tenant_id or version_type != item_type:
                continue
            active = next((version for version in reversed(versions) if version["lifecycleStatus"] == "active"), None)
            if active:
                published.append(_normalize_asset_payload_for_read(item_type, active))
        return visible_items_for_tenant(tenant_id, item_type, sorted(published, key=_sort_key))


class SQLiteDataAssetStore:
    def __init__(self, db_path: str | Path, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS platform_data_asset_items (
                tenant_id TEXT NOT NULL,
                item_type TEXT NOT NULL,
                item_id TEXT NOT NULL,
                title TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, item_type, item_id)
            );

            CREATE INDEX IF NOT EXISTS idx_platform_data_asset_items_tenant_type
                ON platform_data_asset_items(tenant_id, item_type, updated_at DESC);

            CREATE TABLE IF NOT EXISTS platform_raw_table_external_references (
                tenant_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('private', 'shared')),
                schema_fingerprint TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, source_key)
            );
            """
        )
        self._conn.commit()

    def list_bundle(self, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
        return {output_key: self._list(tenant_id, item_type) for item_type, output_key in ASSET_BUNDLE_KEYS.items()}

    def list_published_bundle(self, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
        return {output_key: self._list_published(tenant_id, item_type) for item_type, output_key in ASSET_BUNDLE_KEYS.items()}

    def list_raw_table_external_references(self, tenant_id: str) -> dict[str, dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT source_key, mode, schema_fingerprint, updated_by, updated_at FROM platform_raw_table_external_references WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        return {
            str(row["source_key"]): {
                "sourceKey": str(row["source_key"]), "mode": str(row["mode"]),
                "schemaFingerprint": str(row["schema_fingerprint"]), "updatedBy": str(row["updated_by"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        }

    def set_raw_table_external_reference(
        self, tenant_id: str, source_key: str, mode: str, schema_fingerprint: str, updated_by: str,
    ) -> dict[str, Any]:
        record = _raw_table_external_reference_record(source_key, mode, schema_fingerprint, updated_by)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_raw_table_external_references(
                    tenant_id, source_key, mode, schema_fingerprint, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, source_key) DO UPDATE SET
                    mode = excluded.mode, schema_fingerprint = excluded.schema_fingerprint,
                    updated_by = excluded.updated_by, updated_at = excluded.updated_at
                """,
                (tenant_id, source_key, record["mode"], record["schemaFingerprint"], updated_by, record["updatedAt"]),
            )
        return record

    def seed_defaults(self, tenant_id: str, updated_by: str = "development_seed") -> None:
        for item_type in DEFAULT_ASSET_ITEMS:
            for item in deepcopy(_runtime_default_items(item_type)):
                self.upsert_item(tenant_id, item_type, item, updated_by=updated_by, lifecycle_status="active")

    def seed_missing_defaults(self, tenant_id: str, updated_by: str = "development_seed") -> None:
        seed_platform_capability_catalog(self, tenant_id, updated_by)
        bundle = self.list_bundle(tenant_id)
        for item_type in DEFAULT_ASSET_ITEMS:
            # Tenant-maintained catalogs must not be re-cloned onto every
            # institution after an operator deletes or never created them.
            if item_type in TENANT_MAINTAINED_ASSET_TYPES:
                continue
            existing = {
                str(item.get("id") or ""): item
                for item in bundle.get(ASSET_BUNDLE_KEYS[item_type], [])
            }
            for item in deepcopy(_runtime_default_items(item_type)):
                item_id = str(item.get("id") or "")
                if item_id not in existing:
                    self.upsert_item(tenant_id, item_type, item, updated_by=updated_by, lifecycle_status="active")
                elif item_type == "topic_table" and (
                    item_id == "topic_core_weekly_metrics"
                    or str(existing[item_id].get("updatedBy") or "") == "development_seed"
                ):
                    missing_metadata = {
                        key: item[key]
                        for key in (
                            "name", "description", "systemManaged", "deletable",
                            "datasetId", "metricCodes", "defaultMetrics", "dimensionCodes",
                            "defaultDimensions", "chartTypes", "analysisAngles", "sql", "fields",
                            "fieldExplanations", "applicableScene", "reportReference",
                        )
                        if key in item and existing[item_id].get(key) != item[key]
                    }
                    if missing_metadata:
                        self.upsert_item(
                            tenant_id,
                            item_type,
                            {**existing[item_id], **missing_metadata},
                            updated_by=updated_by,
                            lifecycle_status="active",
                        )

    def purge_retired_sample_assets(self, tenant_id: str) -> int:
        candidates = [
            (item_type, item_id)
            for item_type, item_id in RETIRED_SAMPLE_ASSET_IDS
            if self._conn.execute(
                "SELECT 1 FROM platform_data_asset_items WHERE tenant_id = ? AND item_type = ? AND item_id = ?",
                (tenant_id, item_type, item_id),
            ).fetchone()
        ]
        if not candidates:
            return 0
        with self._conn:
            for item_type, item_id in candidates:
                self._conn.execute(
                    "DELETE FROM platform_data_asset_reviews WHERE tenant_id = ? AND item_type = ? AND item_id = ?",
                    (tenant_id, item_type, item_id),
                )
                self._conn.execute(
                    "DELETE FROM platform_data_asset_versions WHERE tenant_id = ? AND item_type = ? AND item_id = ?",
                    (tenant_id, item_type, item_id),
                )
                self._conn.execute(
                    "DELETE FROM platform_data_asset_items WHERE tenant_id = ? AND item_type = ? AND item_id = ?",
                    (tenant_id, item_type, item_id),
                )
        return len(candidates)

    def upsert_item(
        self,
        tenant_id: str,
        item_type: str,
        item: dict[str, Any],
        updated_by: str | None = None,
        lifecycle_status: str | None = None,
    ) -> dict[str, Any]:
        current_items = self._list(tenant_id, item_type) if item_type in MEMORY_ASSET_TYPES else ()
        fusion = prepare_asset_fusion(item_type, item, current_items)
        normalized = _normalize_item(item_type, fusion.item, updated_by)
        _validate_asset_schema(item_type, normalized)
        status = _asset_status(lifecycle_status)
        submitted_by = updated_by or "system"
        canonical_payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        with self._conn:
            current = self._conn.execute(
                """
                SELECT current_version, lock_version, created_by
                FROM platform_data_asset_items
                WHERE tenant_id = ? AND item_type = ? AND item_id = ?
                """,
                (tenant_id, item_type, normalized["id"]),
            ).fetchone()
            version_number = int(current["current_version"] or 0) + 1 if current else 1
            lock_version = int(current["lock_version"] or 0) + 1 if current else 1
            if status == "active":
                self._conn.execute(
                    """
                    UPDATE platform_data_asset_versions
                    SET lifecycle_status = 'archived'
                    WHERE tenant_id = ? AND item_type = ? AND item_id = ?
                      AND lifecycle_status = 'active'
                    """,
                    (tenant_id, item_type, normalized["id"]),
                )
            self._conn.execute(
                """
                INSERT INTO platform_data_asset_items(
                    tenant_id, item_type, item_id, title, payload, created_by, updated_by, updated_at,
                    lifecycle_status, current_version, schema_version, lock_version,
                    submitted_by, reviewed_by, reviewed_at, published_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, '1.0', ?, ?, NULL, NULL,
                    CASE WHEN ? = 'active' THEN CURRENT_TIMESTAMP ELSE NULL END)
                ON CONFLICT(tenant_id, item_type, item_id) DO UPDATE SET
                    title = excluded.title,
                    payload = excluded.payload,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP,
                    lifecycle_status = excluded.lifecycle_status,
                    current_version = excluded.current_version,
                    schema_version = excluded.schema_version,
                    lock_version = excluded.lock_version,
                    submitted_by = excluded.submitted_by,
                    reviewed_by = NULL,
                    reviewed_at = NULL,
                    published_at = excluded.published_at
                """,
                (
                    tenant_id,
                    item_type,
                    normalized["id"],
                    _item_title(item_type, normalized),
                    canonical_payload,
                    current["created_by"] if current else updated_by,
                    updated_by,
                    status,
                    version_number,
                    lock_version,
                    submitted_by,
                    status,
                ),
            )
            for duplicate_id in fusion.duplicate_ids:
                self._conn.execute(
                    """
                    UPDATE platform_data_asset_items
                    SET lifecycle_status = 'archived', updated_at = CURRENT_TIMESTAMP,
                        lock_version = lock_version + 1
                    WHERE tenant_id = ? AND item_type = ? AND item_id = ?
                    """,
                    (tenant_id, item_type, duplicate_id),
                )
                self._conn.execute(
                    """
                    UPDATE platform_data_asset_versions
                    SET lifecycle_status = 'archived'
                    WHERE tenant_id = ? AND item_type = ? AND item_id = ?
                      AND lifecycle_status IN ('draft', 'review', 'active')
                    """,
                    (tenant_id, item_type, duplicate_id),
                )
            self._conn.execute(
                """
                INSERT INTO platform_data_asset_versions(
                    tenant_id, item_type, item_id, version_number, schema_version,
                    lifecycle_status, title, payload, payload_hash, submitted_by
                ) VALUES (?, ?, ?, ?, '1.0', ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    item_type,
                    normalized["id"],
                    version_number,
                    status,
                    _item_title(item_type, normalized),
                    canonical_payload,
                    payload_hash,
                    submitted_by,
                ),
            )
        return _governed_asset_payload(
            normalized,
            status=status,
            version_number=version_number,
            submitted_by=submitted_by,
            lock_version=lock_version,
        )

    def get_item(self, tenant_id: str, item_type: str, item_id: str) -> dict[str, Any] | None:
        _require_valid_type(item_type)
        row = self._conn.execute(
            """
            SELECT payload, lifecycle_status, current_version, schema_version, lock_version,
                   submitted_by, reviewed_by, reviewed_at, published_at
            FROM platform_data_asset_items
            WHERE tenant_id = ? AND item_type = ? AND item_id = ?
            """,
            (tenant_id, item_type, item_id),
        ).fetchone()
        return _asset_from_row(item_type, row) if row else None

    def review_item(
        self,
        tenant_id: str,
        item_type: str,
        item_id: str,
        *,
        decision: str,
        reviewer_user_id: str,
        comments: str = "",
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        _require_valid_type(item_type)
        _require_review_decision(decision)
        with self._conn:
            row = self._conn.execute(
                """
                SELECT payload, title, lifecycle_status, current_version, schema_version,
                       lock_version, submitted_by
                FROM platform_data_asset_items
                WHERE tenant_id = ? AND item_type = ? AND item_id = ?
                """,
                (tenant_id, item_type, item_id),
            ).fetchone()
            if row is None:
                raise KeyError("data_asset_not_found")
            version_number = int(row["current_version"])
            if expected_version is not None and version_number != int(expected_version):
                raise RuntimeError("data_asset_version_conflict")
            if str(row["lifecycle_status"]) not in {"draft", "review"}:
                raise RuntimeError("data_asset_not_reviewable")
            if str(row["submitted_by"] or "") == reviewer_user_id:
                raise PermissionError("data_asset_four_eyes_required")
            next_status = "active" if decision == "approved" else "rejected"
            reviewed_at = _utc_now()
            if next_status == "active":
                self._conn.execute(
                    """
                    UPDATE platform_data_asset_versions SET lifecycle_status = 'archived'
                    WHERE tenant_id = ? AND item_type = ? AND item_id = ?
                      AND lifecycle_status = 'active' AND version_number <> ?
                    """,
                    (tenant_id, item_type, item_id, version_number),
                )
            cursor = self._conn.execute(
                """
                UPDATE platform_data_asset_versions
                SET lifecycle_status = ?, reviewed_by = ?, reviewed_at = ?, review_comment = ?
                WHERE tenant_id = ? AND item_type = ? AND item_id = ? AND version_number = ?
                  AND lifecycle_status IN ('draft', 'review')
                """,
                (
                    next_status,
                    reviewer_user_id,
                    reviewed_at,
                    str(comments or "")[:2000],
                    tenant_id,
                    item_type,
                    item_id,
                    version_number,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("data_asset_concurrent_review")
            self._conn.execute(
                """
                UPDATE platform_data_asset_items
                SET lifecycle_status = ?, reviewed_by = ?, reviewed_at = ?,
                    published_at = CASE WHEN ? = 'active' THEN ? ELSE published_at END,
                    lock_version = lock_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = ? AND item_type = ? AND item_id = ? AND current_version = ?
                """,
                (
                    next_status,
                    reviewer_user_id,
                    reviewed_at,
                    next_status,
                    reviewed_at,
                    tenant_id,
                    item_type,
                    item_id,
                    version_number,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO platform_data_asset_reviews(
                    review_id, tenant_id, item_type, item_id, version_number,
                    decision, reviewer_user_id, comments
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"asset_review_{uuid4().hex}",
                    tenant_id,
                    item_type,
                    item_id,
                    version_number,
                    decision,
                    reviewer_user_id,
                    str(comments or "")[:2000],
                ),
            )
        reviewed = self.get_item(tenant_id, item_type, item_id)
        assert reviewed is not None
        return reviewed

    def delete_item(self, tenant_id: str, item_type: str, item_id: str) -> bool:
        _require_valid_type(item_type)
        _require_deletable_asset(item_type, item_id)
        with self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM platform_data_asset_items
                WHERE tenant_id = ? AND item_type = ? AND item_id = ?
                """,
                (tenant_id, item_type, item_id),
            )
            if cursor.rowcount > 0:
                self._conn.execute(
                    """
                    UPDATE platform_data_asset_versions
                    SET lifecycle_status = 'archived'
                    WHERE tenant_id = ? AND item_type = ? AND item_id = ?
                      AND lifecycle_status IN ('draft', 'review', 'active')
                    """,
                    (tenant_id, item_type, item_id),
                )
        return cursor.rowcount > 0

    def _list(self, tenant_id: str, item_type: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT payload, lifecycle_status, current_version, schema_version, lock_version,
                   submitted_by, reviewed_by, reviewed_at, published_at
            FROM platform_data_asset_items
            WHERE tenant_id = ? AND item_type = ? AND lifecycle_status <> 'archived'
            ORDER BY updated_at DESC, item_id
            LIMIT 200
            """,
            (tenant_id, item_type),
        ).fetchall()
        return visible_items_for_tenant(
            tenant_id,
            item_type,
            [_asset_from_row(item_type, row) for row in rows],
        )

    def _list_published(self, tenant_id: str, item_type: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT payload, lifecycle_status, version_number AS current_version,
                   schema_version, version_number AS lock_version,
                   submitted_by, reviewed_by, reviewed_at,
                   CASE WHEN lifecycle_status = 'active' THEN reviewed_at ELSE NULL END AS published_at
            FROM platform_data_asset_versions
            WHERE tenant_id = ? AND item_type = ? AND lifecycle_status = 'active'
            ORDER BY reviewed_at DESC, item_id
            LIMIT 200
            """,
            (tenant_id, item_type),
        ).fetchall()
        return visible_items_for_tenant(
            tenant_id,
            item_type,
            [_asset_from_row(item_type, row) for row in rows],
        )


def _normalize_item(item_type: str, item: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
    _require_valid_type(item_type)
    normalized = _normalize_asset_payload_for_read(item_type, item)
    normalized["id"] = str(normalized.get("id") or "").strip()
    if not normalized["id"]:
        raise ValueError("item id is required.")
    normalized["updatedBy"] = updated_by or str(normalized.get("updatedBy") or "")
    return normalized


def _raw_table_external_reference_record(
    source_key: str, mode: str, schema_fingerprint: str, updated_by: str,
) -> dict[str, Any]:
    normalized_key = str(source_key or "").strip()
    normalized_mode = str(mode or "").strip().lower()
    normalized_schema = str(schema_fingerprint or "").strip()
    if not re.fullmatch(r"[a-f0-9]{16,128}", normalized_key):
        raise ValueError("raw_table_external_reference_source_key_invalid")
    if normalized_mode not in {"private", "shared"}:
        raise ValueError("raw_table_external_reference_mode_invalid")
    if not re.fullmatch(r"[a-f0-9]{16,128}", normalized_schema):
        raise ValueError("raw_table_external_reference_schema_invalid")
    if not str(updated_by or "").strip():
        raise ValueError("raw_table_external_reference_actor_required")
    return {
        "sourceKey": normalized_key,
        "mode": normalized_mode,
        "schemaFingerprint": normalized_schema,
        "updatedBy": str(updated_by).strip(),
        "updatedAt": _utc_now(),
    }


def _asset_status(value: str | None) -> str:
    status = str(value or "review").strip().lower()
    if status not in ASSET_LIFECYCLE_STATUSES:
        raise ValueError("invalid_data_asset_lifecycle_status")
    return status


def _governed_asset_payload(
    payload: dict[str, Any],
    *,
    status: str,
    version_number: int,
    submitted_by: str,
    lock_version: int,
    reviewed_by: str = "",
    reviewed_at: str = "",
    published_at: str = "",
) -> dict[str, Any]:
    return {
        **payload,
        "lifecycleStatus": status,
        "assetVersion": int(version_number),
        "schemaVersion": "1.0",
        "lockVersion": int(lock_version),
        "submittedBy": submitted_by,
        "reviewedBy": reviewed_by,
        "reviewedAt": reviewed_at,
        "publishedAt": published_at,
    }


def _asset_from_row(item_type: str, row: sqlite3.Row) -> dict[str, Any]:
    payload = _normalize_asset_payload_for_read(item_type, json.loads(row["payload"]))
    return _governed_asset_payload(
        payload,
        status=str(row["lifecycle_status"]),
        version_number=int(row["current_version"]),
        submitted_by=str(row["submitted_by"] or ""),
        lock_version=int(row["lock_version"]),
        reviewed_by=str(row["reviewed_by"] or ""),
        reviewed_at=str(row["reviewed_at"] or ""),
        published_at=str(row["published_at"] or ""),
    )


def _validate_asset_schema(item_type: str, item: dict[str, Any]) -> None:
    """Validate the stable fields that make an asset safe to version and review.

    The compatibility payload remains JSON, but an arbitrary JSON object can no
    longer enter the reusable planning context.  Type-specific normalized
    entities remain the production target in schema_catalog.py.
    """

    _require_valid_type(item_type)
    if len(json.dumps(item, ensure_ascii=False)) > 1_000_000:
        raise ValueError("data_asset_payload_too_large")
    if item_type == "raw_table":
        _require_text(item, "tableNameEn", "tableNameCn", "source", "description")
        _require_identifier(str(item["tableNameEn"]), "tableNameEn")
        _validate_fields(item.get("fields"), required=True)
        if item.get("metadataOverlayVersion") == 1:
            _require_text(item, "sourceKey", "schemaFingerprint")
            primary_count = 0
            for field in item.get("fields") or ():
                role = str(field.get("semanticRole") or "")
                data_type = str(field.get("type") or "")
                if role not in {"metric", "dimension", "date"}:
                    raise ValueError("raw_table_metadata_role_invalid")
                allowed_types = {"metric": {"integer", "decimal", "rate"}, "dimension": {"string"}, "date": {"date"}}
                if data_type not in allowed_types[role]:
                    raise ValueError("raw_table_metadata_type_invalid")
                if role == "date" and field.get("dateFormat") != "yyyy-MM-dd":
                    raise ValueError("raw_table_metadata_date_format_invalid")
                if field.get("isPrimaryKey"):
                    if role != "dimension":
                        raise ValueError("raw_table_metadata_primary_key_must_be_dimension")
                    primary_count += 1
            if primary_count < 1:
                raise ValueError("raw_table_metadata_primary_key_required")
        return
    if item_type == "topic_table":
        _require_text(item, "name", "code", "description", "sql")
        _require_identifier(str(item["code"]), "code")
        task_bound = bool(
            item.get("tenantBindingMode") == "analysis_task_scoped"
            and str(item.get("analysisTaskId") or "").strip()
            and str(item.get("executionId") or "").strip()
            and str(item.get("evidenceId") or "").strip()
            and isinstance(item.get("sourceSnapshot"), dict)
            and item.get("sourceSnapshot")
        )
        _validate_topic_sql(str(item["sql"]), allow_analysis_task_binding=task_bound)
        _validate_fields(item.get("fields"), required=True, allow_executed_column_names=task_bound)
        return
    if item_type == "intent":
        _require_text(item, "scenario", "purpose", "description", "keywords")
        return
    if item_type == "analysis_experience":
        if not str(item.get("title") or item.get("name") or "").strip():
            raise ValueError("data_asset_missing_field:analysis_experience.title")
        if not str(item.get("steps") or item.get("analysisSteps") or "").strip():
            raise ValueError("data_asset_missing_field:analysis_experience.steps")
        return
    if item_type == "user_behavior_habit":
        _require_text(item, "title", "description", "sourceVersionId", "evidence")
        if _habit_type(item.get("habitType")) != str(item.get("habitType") or "").strip():
            raise ValueError("data_asset_invalid_habit_type")
        return
    if item_type == "knowledge_file":
        _require_text(item, "title")
        return
    if item_type == "analysis_skill":
        _require_text(item, "name", "category", "description", "analysisMethod", "documentAbstraction", "viewpointStrategy")
        if str(item.get("category")) not in {"场景", "主题"}:
            raise ValueError("data_asset_invalid_analysis_skill_category")
        display_location = str(item.get("displayLocation") or "intelligent_analysis")
        if display_location not in {"intelligent_analysis", "hidden"}:
            raise ValueError("data_asset_invalid_analysis_skill_display_location")
        canonical_skill_id = canonical_core_topic_skill_id(item)
        if canonical_skill_id and str(item.get("id") or "") != canonical_skill_id:
            raise ValueError(f"data_asset_duplicate_core_topic_skill:{canonical_skill_id}")
        if str(item.get("category")) == "场景":
            _require_text(item, "outputFormat")
        return
    if item_type == "external_tool":
        _require_text(item, "name", "provider", "toolType", "description")
        if item.get("enabled") is True:
            provider = str(item.get("provider") or "").strip().lower()
            endpoint = str(item.get("endpoint") or "").strip()
            if provider != "internal agent" and not endpoint:
                raise ValueError("data_asset_external_tool_endpoint_required")
        return
    if item_type == "analysis_shortcut":
        _require_text(item, "title", "query")
        return
    if item_type == "conclusion_rule":
        _require_text(item, "name", "purpose", "datasetId", "datasetName", "datasetKind", "skillId")
        if str(item.get("purpose") or "") != "conclusion_generation":
            raise ValueError("conclusion_rule_purpose_invalid")
        if str(item.get("datasetKind") or "") not in {"raw_table", "topic_table", "page_data"}:
            raise ValueError("conclusion_rule_dataset_kind_invalid")
        rules = item.get("metricRules")
        if not isinstance(rules, list) or not rules or len(rules) > 40:
            raise ValueError("conclusion_rule_metric_rules_invalid")
        seen: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError("conclusion_rule_metric_rule_invalid")
            _require_text(rule, "id", "metricField", "performance", "operator", "conclusion")
            rule_id = str(rule.get("id") or "")
            if rule_id in seen:
                raise ValueError("conclusion_rule_metric_rule_duplicate")
            seen.add(rule_id)
            if str(rule.get("operator") or "") not in {"gt", "gte", "eq", "lte", "lt", "between"}:
                raise ValueError("conclusion_rule_operator_invalid")
            try:
                float(rule.get("threshold"))
                if str(rule.get("operator") or "") == "between":
                    float(rule.get("thresholdEnd"))
            except (TypeError, ValueError):
                raise ValueError("conclusion_rule_threshold_invalid") from None
        return
    if item_type == "page_data":
        _require_text(item, "name", "sourceKey", "schemaFingerprint", "sourceTableName", "visualizationType")
        pages = item.get("targetPages")
        scope = str(item.get("institutionScope") or "single_institution")
        if scope not in {"single_institution", "multi_institution", "customer_segment"}:
            raise ValueError("page_data_institution_scope_invalid")
        allowed_pages = (
            {"weekly_report", "institution_supervision"} if scope == "single_institution"
            else {"dashboard"} if scope == "multi_institution"
            else {"customer_segment_analysis"}
        )
        if not isinstance(pages, list) or len(pages) != 1 or str(pages[0]) not in allowed_pages:
            raise ValueError("page_data_target_pages_invalid")
        source_fields = item.get("sourceFields")
        _validate_fields(source_fields, required=True)
        available = {str(field.get("fieldNameEn") or "") for field in source_fields if isinstance(field, dict)}
        metrics = _validated_page_data_fields(item.get("metricFields"), available, required=True, kind="metric")
        dimensions = _validated_page_data_fields(item.get("dimensionFields"), available, required=True, kind="dimension")
        if set(metrics) & set(dimensions):
            raise ValueError("page_data_metric_dimension_overlap")
        allowed_styles = {"kpi", "line", "area", "column", "bar", "stacked_bar", "combo", "donut", "scatter", "funnel", "treemap", "radar", "table", "pivot"}
        if str(item.get("visualizationType")) not in allowed_styles:
            raise ValueError("page_data_visualization_type_invalid")
        if scope == "multi_institution":
            if str(item.get("relationshipGroupId") or "") != str(item.get("sourceKey") or ""):
                raise ValueError("multi_institution_page_data_relationship_invalid")
            sources = item.get("institutionSources")
            if not isinstance(sources, list) or len(sources) < 2:
                raise ValueError("multi_institution_page_data_sources_invalid")
            tenant_ids = [str(source.get("tenantId") or "") for source in sources if isinstance(source, dict)]
            source_refs = [(str(source.get("tenantId") or ""), str(source.get("sourceKey") or "")) for source in sources if isinstance(source, dict)]
            if (
                len(tenant_ids) != len(sources)
                or any(not tenant_id for tenant_id in tenant_ids)
                or len(set(tenant_ids)) < 2
                or len(source_refs) != len(set(source_refs))
                or any(not source_key for _, source_key in source_refs)
            ):
                raise ValueError("multi_institution_page_data_sources_invalid")
        if scope == "customer_segment":
            customer_key = str(item.get("customerKeyField") or "").strip()
            primary_fields = [
                str(field.get("fieldNameEn") or "").strip()
                for field in source_fields
                if isinstance(field, dict) and bool(field.get("isPrimaryKey"))
            ]
            if len(primary_fields) != 1 or customer_key != primary_fields[0]:
                raise ValueError("customer_segment_detail_table_required")
        return
    if item_type == "table_relationship":
        _require_text(item, "name", "relationshipScope")
        relationship_scope = str(item.get("relationshipScope") or "")
        if relationship_scope not in {"single_institution", "multi_institution"}:
            raise ValueError("table_relationship_scope_invalid")
        nodes = item.get("nodes")
        edges = item.get("edges")
        if not isinstance(nodes, list) or len(nodes) < 2 or len(nodes) > 12:
            raise ValueError("table_relationship_nodes_invalid")
        if not isinstance(edges, list) or not edges or len(edges) > 24:
            raise ValueError("table_relationship_edges_invalid")
        node_ids: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("table_relationship_node_invalid")
            _require_text(node, "id", "tenantId", "institutionName", "sourceKey", "sourceTableName", "schemaFingerprint")
            node_id = str(node["id"])
            if node_id in node_ids:
                raise ValueError("table_relationship_duplicate_node")
            node_ids.add(node_id)
            _validate_fields(node.get("fields"), required=True)
        tenant_ids = {str(node.get("tenantId") or "") for node in nodes if isinstance(node, dict)}
        if (relationship_scope == "multi_institution") != (len(tenant_ids) > 1):
            raise ValueError("table_relationship_scope_tenant_mismatch")
        edge_ids: set[str] = set()
        for edge in edges:
            if not isinstance(edge, dict):
                raise ValueError("table_relationship_edge_invalid")
            _require_text(edge, "id", "sourceNodeId", "sourceField", "targetNodeId", "targetField")
            edge_id = str(edge["id"])
            if edge_id in edge_ids:
                raise ValueError("table_relationship_duplicate_edge")
            edge_ids.add(edge_id)
            if str(edge["sourceNodeId"]) not in node_ids or str(edge["targetNodeId"]) not in node_ids:
                raise ValueError("table_relationship_edge_node_invalid")
        return


def _require_text(item: dict[str, Any], *fields: str) -> None:
    for field in fields:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"data_asset_missing_field:{field}")
        if len(value) > 100_000:
            raise ValueError(f"data_asset_field_too_large:{field}")


def _require_identifier(value: str, field: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,199}", value.strip()):
        raise ValueError(f"data_asset_invalid_identifier:{field}")


def _validate_fields(value: Any, *, required: bool, allow_executed_column_names: bool = False) -> None:
    if not isinstance(value, list) or (required and not value):
        raise ValueError("data_asset_fields_required")
    seen: set[str] = set()
    for field in value:
        if not isinstance(field, dict):
            raise ValueError("data_asset_field_must_be_object")
        name = str(field.get("fieldNameEn") or "").strip()
        if allow_executed_column_names:
            if not name:
                raise ValueError("data_asset_fields_required")
        else:
            _require_identifier(name, "fieldNameEn")
        if name in seen:
            raise ValueError(f"data_asset_duplicate_field:{name}")
        seen.add(name)
        if not str(field.get("type") or "").strip():
            raise ValueError(f"data_asset_field_type_required:{name}")


def _validated_page_data_fields(value: Any, available: set[str], *, required: bool, kind: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"page_data_{kind}_fields_invalid")
    fields = [str(field or "").strip() for field in value]
    if required and not fields:
        raise ValueError(f"page_data_{kind}_fields_required")
    if len(fields) != len(set(fields)) or any(not field or field not in available for field in fields):
        raise ValueError(f"page_data_{kind}_fields_invalid")
    return fields


def _validate_topic_sql(sql: str, *, allow_analysis_task_binding: bool = False) -> None:
    normalized = re.sub(r"/\*.*?\*/|--[^\n]*", " ", sql, flags=re.DOTALL).strip()
    if not re.match(r"^(select|with)\b", normalized, flags=re.IGNORECASE):
        raise ValueError("topic_table_sql_must_be_select")
    if re.search(r"\b(insert|update|delete|merge|drop|alter|truncate|attach|pragma|grant|revoke)\b", normalized, flags=re.IGNORECASE):
        raise ValueError("topic_table_sql_contains_forbidden_statement")
    if ";" in normalized.rstrip(";"):
        raise ValueError("topic_table_sql_multiple_statements_forbidden")
    if not allow_analysis_task_binding and not re.search(r"(?::tenant_id\b|\btenant_id\s*=\s*\?)", normalized, flags=re.IGNORECASE):
        raise ValueError("topic_table_sql_tenant_binding_required")


def _require_review_decision(decision: str) -> None:
    if decision not in {"approved", "rejected", "changes_required"}:
        raise ValueError("invalid_data_asset_review_decision")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_asset_payload_for_read(item_type: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    if item_type == "topic_table":
        normalized["fields"] = _normalize_topic_fields(normalized)
    if item_type == "analysis_experience":
        normalized = _normalize_analysis_experience(normalized)
    if item_type == "user_behavior_habit":
        normalized = _normalize_behavior_habit(normalized)
    return normalized


def _normalize_analysis_experience(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or item.get("name") or item.get("id") or "").strip()
    description = str(item.get("description") or item.get("rules") or item.get("commonConclusions") or "").strip()
    steps = item.get("analysis_steps")
    if isinstance(steps, list):
        step_text = "\n".join(str(step) for step in steps if str(step).strip())
    else:
        step_text = str(item.get("steps") or "").strip()
    metrics = item.get("related_metrics")
    if isinstance(metrics, list):
        metrics_text = ", ".join(str(metric) for metric in metrics if str(metric).strip())
    else:
        metrics_text = str(item.get("metrics") or item.get("relatedMetrics") or "").strip()
    return {
        **item,
        "id": str(item.get("id") or "").strip(),
        "title": title,
        "name": str(item.get("name") or title).strip(),
        "description": description,
        "analysisSteps": step_text,
        "steps": str(item.get("steps") or step_text).strip(),
        "scenario": str(item.get("scenario") or item.get("relatedIntent") or "经营周报分析").strip(),
        "relatedMetrics": metrics_text,
        "metrics": str(item.get("metrics") or metrics_text).strip(),
        "sourceVersionId": str(item.get("sourceVersionId") or item.get("source_version_id") or "").strip(),
        "sourceVersionName": str(item.get("sourceVersionName") or "").strip(),
        "evidence": str(item.get("evidence") or "").strip(),
        "firstSeenAt": str(item.get("firstSeenAt") or item.get("first_seen_at") or "").strip(),
        "lastSeenAt": str(item.get("lastSeenAt") or item.get("last_seen_at") or item.get("updatedAt") or "").strip(),
        "frequency": _int(item.get("frequency"), 1),
        "weight": _float(item.get("weight"), 0),
        "status": str(item.get("status") or "当前有效").strip(),
        "confidence": _float(item.get("confidence"), 0),
        "enabled": bool(item.get("enabled", True)),
    }


def _normalize_behavior_habit(item: dict[str, Any]) -> dict[str, Any]:
    metrics = item.get("related_metrics")
    orgs = item.get("related_orgs")
    return {
        **item,
        "id": str(item.get("id") or "").strip(),
        "title": str(item.get("title") or item.get("id") or "").strip(),
        "habitType": _habit_type(item.get("habitType") or item.get("habit_type")),
        "description": str(item.get("description") or "").strip(),
        "behaviorDetail": str(item.get("behaviorDetail") or item.get("behavior_detail") or "").strip(),
        "sourceVersionId": str(item.get("sourceVersionId") or item.get("source_version_id") or "").strip(),
        "sourceVersionName": str(item.get("sourceVersionName") or "").strip(),
        "evidence": str(item.get("evidence") or "").strip(),
        "relatedMetrics": ", ".join(str(metric) for metric in metrics) if isinstance(metrics, list) else str(item.get("relatedMetrics") or "").strip(),
        "relatedOrgs": ", ".join(str(org) for org in orgs) if isinstance(orgs, list) else str(item.get("relatedOrgs") or "").strip(),
        "firstSeenAt": str(item.get("firstSeenAt") or item.get("first_seen_at") or "").strip(),
        "lastSeenAt": str(item.get("lastSeenAt") or item.get("last_seen_at") or item.get("updatedAt") or "").strip(),
        "frequency": _int(item.get("frequency"), 1),
        "weight": _float(item.get("weight"), 0),
        "status": str(item.get("status") or "当前有效").strip(),
        "confidence": _float(item.get("confidence"), 0),
        "updatedAt": str(item.get("updatedAt") or "").strip(),
    }


def _normalize_topic_fields(topic: dict[str, Any]) -> list[dict[str, Any]]:
    fields = topic.get("fields")
    if isinstance(fields, list):
        return [_normalize_field(field) for field in fields if isinstance(field, dict)]
    field_names = [
        field.strip()
        for field in str(fields or "").replace("，", ",").replace("、", ",").split(",")
        if field.strip()
    ]
    explanations = [
        field.strip()
        for field in str(topic.get("fieldExplanations") or "").replace("，", ",").replace("、", ",").split(",")
        if field.strip()
    ]
    return [
        _normalize_field(
            {
                "fieldNameEn": field_name,
                "fieldNameCn": explanations[index] if index < len(explanations) else field_name,
                "type": _infer_topic_field_type(field_name),
                "explanation": explanations[index] if index < len(explanations) else "待补充字段语义解释。",
                "exampleUsage": "智能分析、经营周报、主题表复用",
            }
        )
        for index, field_name in enumerate(field_names)
    ]


def _normalize_field(field: dict[str, Any]) -> dict[str, Any]:
    return {
        **field,
        "fieldNameEn": str(field.get("fieldNameEn") or "").strip(),
        "fieldNameCn": str(field.get("fieldNameCn") or field.get("fieldNameEn") or "").strip(),
        "type": str(field.get("type") or "string").strip(),
        "explanation": str(field.get("explanation") or "待补充字段语义解释。").strip(),
        "exampleUsage": str(field.get("exampleUsage") or "智能分析、经营周报、主题表复用").strip(),
    }


def _infer_topic_field_type(field_name: str) -> str:
    lowered = field_name.lower()
    if "date" in lowered or "time" in lowered or "日期" in field_name or "时间" in field_name:
        return "date"
    if any(token in lowered for token in ("amount", "balance", "rate", "count", "num")) or any(
        token in field_name for token in ("金额", "余额", "率", "数")
    ):
        return "decimal"
    return "string"


def _require_valid_type(item_type: str) -> None:
    if item_type not in ASSET_TYPES:
        raise ValueError(f"unsupported data asset item type: {item_type}")


def _item_title(item_type: str, item: dict[str, Any]) -> str:
    if item_type == "raw_table":
        return str(item.get("tableNameCn") or item.get("tableNameEn") or item["id"])
    if item_type == "topic_table":
        return str(item.get("name") or item.get("code") or item["id"])
    if item_type == "intent":
        return str(item.get("purpose") or item.get("scenario") or item["id"])
    if item_type == "analysis_experience":
        return str(item.get("title") or item.get("name") or item["id"])
    if item_type == "user_behavior_habit":
        return str(item.get("title") or item["id"])
    if item_type in {"analysis_skill", "external_tool"}:
        return str(item.get("name") or item["id"])
    if item_type == "analysis_shortcut":
        return str(item.get("title") or item["id"])
    if item_type == "page_data":
        return str(item.get("name") or item.get("sourceTableName") or item["id"])
    if item_type == "table_relationship":
        return str(item.get("name") or item["id"])
    if item_type == "conclusion_rule":
        return str(item.get("name") or item.get("datasetName") or item["id"])
    return str(item.get("title") or item["id"])


def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("updatedAt") or ""), str(item.get("id") or ""))


def _habit_type(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in {"分析习惯", "运营习惯", "汇报习惯"} else "分析习惯"


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

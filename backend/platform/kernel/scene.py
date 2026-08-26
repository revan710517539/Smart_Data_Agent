from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCENE_INTENT_SKILL_ID = "scene-analysis-intent"
PLANNER_SKILL_IDS = frozenset({SCENE_INTENT_SKILL_ID})

SURFACE_CHART_FOLLOWUP = "chart_followup"
SURFACE_PAGE_RAIL = "page_rail"
SURFACE_SELF_ANALYSIS = "self_analysis"
SURFACE_TEXTBOX_VOICE = "textbox_voice"
SURFACE_CHART_VOICE = "chart_voice"

VOICE_NONE = "none"
VOICE_CHART_CONTROL = "chart_control"
VOICE_TEXTBOX_RECORD = "textbox_record"
VOICE_TEXTBOX_ANALYZE = "textbox_analyze"

KIND_DESCRIPTIVE = "descriptive"
KIND_ATTRIBUTION = "attribution"
KIND_PREDICTIVE = "predictive"

KIND_SKILL_IDS = {
    KIND_DESCRIPTIVE: "topic-descriptive",
    KIND_ATTRIBUTION: "topic-attribution",
    KIND_PREDICTIVE: "topic-predictive",
}
SURFACE_SKILL_IDS = {
    SURFACE_CHART_FOLLOWUP: "scene-chart-followup",
    SURFACE_PAGE_RAIL: "scene-page-rail",
    SURFACE_TEXTBOX_VOICE: "scene-textbox-voice",
    SURFACE_SELF_ANALYSIS: "scene-self-analysis",
}

_PREDICTIVE_TERMS = ("预测", "预估", "预计", "展望", "未来", "forecast", "将会", "下月", "下季度", "明年")
_ATTRIBUTION_TERMS = ("为什么", "为何", "原因", "归因", "贡献", "拆解", "导致", "驱动", "因为")
_DESCRIPTIVE_TERMS = ("描述", "现状", "结构", "分布", "多少", "排名", "趋势", "对比", "概览", "情况", "变化")
_RECORD_TERMS = ("记下", "记录", "写入", "输入到", "写到", "加上", "标题写成", "记一下", "备忘", "原文")
_ANALYZE_TERMS = ("分析", "看看", "解读", "判断", "结论", "诊断")
_EXPLICIT_SKILL_TERMS = {
    "topic-descriptive": ("描述性分析", "描述分析"),
    "topic-attribution": ("归因分析", "贡献分析", "原因拆解"),
    "topic-predictive": ("预测分析", "预测模型"),
}


@dataclass
class SceneDecision:
    surface: str
    voice_mode: str
    action: str
    analysis_kinds: tuple[str, ...]
    skill_ids: tuple[str, ...] = ()
    dataset_scope: str = "page"
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "voice_mode": self.voice_mode,
            "action": self.action,
            "analysis_kinds": list(self.analysis_kinds),
            "skill_ids": list(self.skill_ids),
            "dataset_scope": self.dataset_scope,
            "reason": self.reason,
            "planner_skill_id": SCENE_INTENT_SKILL_ID,
        }


def classify_analysis_scene(question: str, page_context: dict[str, Any] | None = None) -> SceneDecision:
    context = page_context if isinstance(page_context, dict) else {}
    text = str(question or "").strip()
    hint = str(context.get("analysis_scene_hint") or "").strip()
    card_type = str(context.get("visual_card_type") or context.get("card_type") or "").strip().lower()
    trigger = str(context.get("analysis_trigger") or "").strip()
    voice_surface = str(context.get("voice_surface") or "").strip()
    visual_scope = str(context.get("visual_analysis_scope") or "").strip()
    chart_bound = bool(context.get("chart_bound_source"))
    route = str(context.get("route") or "").strip()
    selected_tables = context.get("selected_data_tables") if isinstance(context.get("selected_data_tables"), list) else []
    page_sources = context.get("visual_analysis_sources") if isinstance(context.get("visual_analysis_sources"), list) else []

    kinds = _analysis_kinds(text)
    if hint in {SURFACE_CHART_FOLLOWUP, SURFACE_PAGE_RAIL, SURFACE_SELF_ANALYSIS, SURFACE_TEXTBOX_VOICE, SURFACE_CHART_VOICE}:
        surface = hint
    elif card_type == "text" and (voice_surface == "text" or trigger.startswith("realtime_voice")):
        surface = SURFACE_TEXTBOX_VOICE
    elif voice_surface == "chart" and trigger.startswith("realtime_voice"):
        surface = SURFACE_CHART_VOICE
    elif visual_scope == "chart" or chart_bound:
        surface = SURFACE_CHART_FOLLOWUP
    elif route.startswith("self-analysis"):
        surface = SURFACE_SELF_ANALYSIS
    elif page_sources or str(context.get("workspace_id") or "").strip() or str(context.get("thread_id") or "").strip():
        surface = SURFACE_PAGE_RAIL
    elif selected_tables:
        surface = SURFACE_SELF_ANALYSIS
    else:
        surface = SURFACE_SELF_ANALYSIS

    if surface == SURFACE_CHART_VOICE:
        voice_mode = VOICE_CHART_CONTROL
        action = "morph_chart"
        dataset_scope = "chart"
        reason = "非文本可视化实时语音用于更换图表形态、指标或维度。"
    elif surface == SURFACE_TEXTBOX_VOICE:
        # A visualization text box is an authoring surface, never an analysis
        # trigger.  Words such as “分析” or “为什么” are part of the dictated
        # text and must not silently start a model run.
        voice_mode = VOICE_TEXTBOX_RECORD
        action = "record"
        dataset_scope = "card"
        reason = "文本框实时语音仅做转写，将口述文字写入光标所在标题或正文，不触发数据分析。"
        kinds = ()
    elif surface == SURFACE_CHART_FOLLOWUP:
        voice_mode = VOICE_NONE
        action = "analyze"
        dataset_scope = "chart"
        reason = "可视化追问进入 AI 分析栏，仅针对当前图表绑定的单个数据集。"
    elif surface == SURFACE_PAGE_RAIL:
        voice_mode = VOICE_NONE
        action = "analyze"
        dataset_scope = "page"
        reason = "未选中单个组件时，AI 分析栏汇总当前页全部可视化数据。"
    else:
        voice_mode = VOICE_NONE
        action = "analyze"
        dataset_scope = "selected" if selected_tables else "page"
        reason = "智能分析主查询按当前页已选数据表进行分析。"

    if action == "analyze" and not kinds:
        kinds = (KIND_DESCRIPTIVE,)
    return SceneDecision(
        surface=surface,
        voice_mode=voice_mode,
        action=action,
        analysis_kinds=kinds,
        dataset_scope=dataset_scope,
        reason=reason,
        detail={"question": text[:200], "visual_analysis_scope": visual_scope, "card_type": card_type},
    )


def plan_analysis_skills(
    decision: SceneDecision,
    catalog: list[dict[str, Any]] | None,
    question: str,
) -> SceneDecision:
    catalog_items = [item for item in (catalog or []) if isinstance(item, dict) and item.get("enabled") is not False]
    planned: list[str] = [SCENE_INTENT_SKILL_ID]
    surface_skill = SURFACE_SKILL_IDS.get(decision.surface)
    if surface_skill:
        planned.append(surface_skill)
    if decision.action != "analyze":
        return SceneDecision(
            surface=decision.surface,
            voice_mode=decision.voice_mode,
            action=decision.action,
            analysis_kinds=decision.analysis_kinds,
            skill_ids=tuple(dict.fromkeys(item for item in planned if item)),
            dataset_scope=decision.dataset_scope,
            reason=decision.reason,
            detail=decision.detail,
        )

    text = str(question or "")
    catalog_by_id = {str(item.get("id") or ""): item for item in catalog_items if str(item.get("id") or "").strip()}
    for kind in decision.analysis_kinds:
        default_id = KIND_SKILL_IDS.get(kind, "")
        tenant_match = _first_matching_skill(catalog_items, text, kind)
        if tenant_match:
            planned.append(str(tenant_match.get("id") or ""))
        elif default_id and (not catalog_items or default_id in catalog_by_id):
            planned.append(default_id)

    extras = _question_matched_skills(catalog_items, text)
    for item in extras:
        skill_id = str(item.get("id") or "")
        if skill_id and skill_id not in planned and skill_id not in KIND_SKILL_IDS.values():
            planned.append(skill_id)
        if len(planned) >= 5:
            break
    return SceneDecision(
        surface=decision.surface,
        voice_mode=decision.voice_mode,
        action=decision.action,
        analysis_kinds=decision.analysis_kinds,
        skill_ids=tuple(dict.fromkeys(item for item in planned if item)),
        dataset_scope=decision.dataset_scope,
        reason=decision.reason,
        detail=decision.detail,
    )


def apply_analysis_scene(
    question: str,
    page_context: dict[str, Any],
    catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    next_context = dict(page_context or {})
    decision = plan_analysis_skills(classify_analysis_scene(question, next_context), catalog, question)
    next_context["analysis_scene"] = decision.as_dict()
    existing = [item for item in next_context.get("analysis_context_skills") or [] if isinstance(item, dict)]
    selected = next_context.get("analysis_skill") if isinstance(next_context.get("analysis_skill"), dict) else None
    seen = {str(item.get("id") or "").strip() for item in existing if str(item.get("id") or "").strip()}
    if selected:
        selected_id = str(selected.get("id") or "").strip()
        if selected_id:
            seen.add(selected_id)
    extras: list[dict[str, Any]] = []
    # Explicit page/user Skills keep their order, while scene and topic Skills
    # are appended as runtime dispatch candidates. This is the single shared
    # dispatch path for both chart and page-rail analysis.
    for skill_id in decision.skill_ids:
        if not skill_id or skill_id in PLANNER_SKILL_IDS or skill_id in seen:
            continue
        extras.append({"id": skill_id})
        seen.add(skill_id)
        if len(existing) + len(extras) >= 8:
            break
    next_context["analysis_context_skills"] = [*existing, *extras][:8]
    # Only make an automatic scene Skill the primary selection when the caller
    # did not explicitly provide any Skill. Otherwise the second governed
    # resolution pass would move that automatic Skill in front of the user's
    # ordered page/Skill context.
    if not existing and not (selected and str(selected.get("id") or "").strip()) and extras:
        next_context["analysis_skill"] = extras[0]
    return next_context


def analysis_kind_instructions(kinds: list[str] | tuple[str, ...] | None) -> str:
    labels = []
    for kind in kinds or (KIND_DESCRIPTIVE,):
        if kind == KIND_ATTRIBUTION:
            labels.append("归因分析：拆解贡献与对比基线，不把相关性写成因果。")
        elif kind == KIND_PREDICTIVE:
            labels.append("预测分析：给出区间、关键假设和失效条件，不把点预测当成已发生事实。")
        else:
            labels.append("描述性分析：陈述现状、结构、分布、趋势、极值和异常，不解释因果。")
    return " ".join(labels)


def _analysis_kinds(text: str) -> tuple[str, ...]:
    kinds: list[str] = []
    if any(term in text for term in _PREDICTIVE_TERMS):
        kinds.append(KIND_PREDICTIVE)
    if any(term in text for term in _ATTRIBUTION_TERMS):
        kinds.append(KIND_ATTRIBUTION)
    if any(term in text for term in _DESCRIPTIVE_TERMS) or not kinds:
        kinds.insert(0, KIND_DESCRIPTIVE)
    if KIND_DESCRIPTIVE in kinds and (KIND_ATTRIBUTION in kinds or KIND_PREDICTIVE in kinds) and not any(term in text for term in _DESCRIPTIVE_TERMS):
        kinds = [item for item in kinds if item != KIND_DESCRIPTIVE]
        if not kinds:
            kinds = [KIND_DESCRIPTIVE]
    return tuple(dict.fromkeys(kinds))


def _is_tenant_authored(item: dict[str, Any]) -> bool:
    author = str(item.get("updatedBy") or item.get("updated_by") or "").strip()
    return author not in {"", "system", "development_seed"}


def _skill_blob(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("id", "name", "description", "analysisMethod", "viewpointStrategy", "category")
    )


def _first_matching_skill(catalog: list[dict[str, Any]], question: str, kind: str) -> dict[str, Any] | None:
    default_id = KIND_SKILL_IDS.get(kind, "")
    kind_label = {"descriptive": "描述", "attribution": "归因", "predictive": "预测"}.get(kind, "")
    for item in catalog:
        skill_id = str(item.get("id") or "")
        if skill_id in PLANNER_SKILL_IDS:
            continue
        if not _is_tenant_authored(item):
            continue
        blob = _skill_blob(item)
        if skill_id == default_id or (kind_label and kind_label in blob) or (question and any(token and token in question for token in (item.get("name"),))):
            return item
    return None


def _question_matched_skills(catalog: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    text = str(question or "").strip()
    if len(text) < 2:
        return []
    hits: list[dict[str, Any]] = []
    for item in catalog:
        skill_id = str(item.get("id") or "")
        name = str(item.get("name") or "").strip()
        if not skill_id or skill_id in PLANNER_SKILL_IDS or not name:
            continue
        if name in text or (len(name) >= 4 and name[:4] in text):
            hits.append(item)
    return hits

from __future__ import annotations

from typing import Any

from backend.platform.api.support import send_route_exception
from backend.platform.settings import call_model_text_completion, select_model_for_application


def handle_supervisor_chat(handler: Any) -> None:
    try:
        context = handler._request_context()
        handler._require_application_permission(context, "execute")
        payload = handler._read_json()
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValueError("supervisor_question_required")
        page_path = str(payload.get("page_path") or "").strip() or "/"
        institution = str(payload.get("institution") or "").strip() or context.tenant_id
        selection = payload.get("model_application_selection")
        model = select_model_for_application(
            handler.services.system_config_store,
            context.tenant_id,
            "intelligent_analysis_reasoning",
            selection if isinstance(selection, dict) else None,
            user_id=context.user_id,
            reveal_secret=True,
        )
        if model is None:
            raise ValueError("model_application_module_not_ready:智能分析推理分析")
        history = _conversation_excerpt(payload.get("conversation"))
        prompt = (
            "你是 Smart Data Agent 的系统 Agent 总管，面向银行经营分析操作员对话。\n"
            f"当前机构：{institution}\n"
            f"当前页面：{page_path}\n"
            "只根据系统能力和已给出的对话上下文回答。不要编造业务数据、指标数值、机构排名或未查询到的结论。\n"
            "如果用户需要查数、出图或正式分析，明确提示先到智能分析选择当前机构数据表后再提问。\n"
            "如果用户只是寒暄或询问你能做什么，用简短中文说明：你可以介绍当前页操作、查询指标口径、记忆、Skill，并打开已有页面；写入、删除、发布必须由用户确认。\n"
            f"{history}"
            f"用户：{question}\n"
            "总管："
        )
        completion = call_model_text_completion(model, prompt, max_tokens=800)
        reply = str(completion.get("response_text") or "").strip()
        status = str(completion.get("status") or "failed")
        if status != "connected" or not reply:
            message = str(completion.get("message") or "").strip() or "当前所选模型没有返回可用回复，请检查左下角模型后重试。"
            handler._send_json({
                "tenant_id": context.tenant_id,
                "status": status,
                "reply": message,
                "error_code": completion.get("error_code") or "supervisor_model_unavailable",
                "used_model": completion.get("used_model") or "",
                "model_id": completion.get("model_id") or model.get("id") or "",
            })
            return
        handler._send_json({
            "tenant_id": context.tenant_id,
            "status": "connected",
            "reply": reply,
            "used_model": completion.get("used_model") or "",
            "model_id": completion.get("model_id") or model.get("id") or "",
        })
    except Exception as exc:
        send_route_exception(handler, exc)


def _conversation_excerpt(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    lines: list[str] = []
    for item in value[-8:]:
        if not isinstance(item, dict):
            continue
        role = "用户" if str(item.get("role") or "") == "user" else "总管"
        text = str(item.get("content") or "").strip()
        if text:
            lines.append(f"{role}：{text[:400]}")
    return ("最近对话：\n" + "\n".join(lines) + "\n") if lines else ""

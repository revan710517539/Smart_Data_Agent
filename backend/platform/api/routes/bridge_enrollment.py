from __future__ import annotations

from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
import json
from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import send_route_exception
from backend.platform.security import AuthenticationError


def handle_bridge_enrollment_start(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=32 * 1024)
        enrollment = handler.services.bridge_auth_store.start_enrollment(
            str(payload.get("channel") or ""),
            str(payload.get("device_name") or payload.get("deviceName") or ""),
            str(payload.get("verifier_hash") or payload.get("verifierHash") or ""),
        )
        user_code = str(enrollment["user_code"])
        handler._send_json(
            {
                **enrollment,
                "verification_uri": "/bridge-authorize",
                "verification_uri_complete": f"/bridge-authorize?user_code={user_code}",
                "verification_api_uri_complete": f"/api/integrations/bridge/enrollment/verify?user_code={user_code}",
            },
            HTTPStatus.CREATED,
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_enrollment_verify(handler: Any, query: str) -> None:
    try:
        user_code = str((parse_qs(query).get("user_code") or [""])[0]).strip()
        preview = handler.services.bridge_auth_store.enrollment_preview(user_code)
        _send_approval_page(handler, user_code, preview)
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_enrollment_preview(handler: Any, query: str) -> None:
    try:
        user_code = str((parse_qs(query).get("user_code") or [""])[0]).strip()
        handler._send_json(handler.services.bridge_auth_store.enrollment_preview(user_code))
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_enrollment_approve(handler: Any) -> None:
    try:
        _require_explicit_browser_session(handler)
        payload = handler._read_json(max_bytes=16 * 1024)
        context = handler._request_context(payload)
        handler._require_asset_permission(context, "read")
        handler._require_report_permission(context, "create")
        approved = handler.services.bridge_auth_store.approve_enrollment(
            str(payload.get("user_code") or payload.get("userCode") or ""),
            context.tenant_id,
            context.user_id,
            context.user_id,
        )
        handler.services.audit_store.write(
            context.tenant_id,
            context.user_id,
            "bridge.enrollment.approved",
            "bridge_device",
            f"{approved['channel']}:{approved['device_name']}",
            {"channel": approved["channel"], "device_name": approved["device_name"]},
            handler.client_address[0] if handler.client_address else "",
        )
        handler._send_json({"approved": True, **approved})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_enrollment_poll(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=16 * 1024)
        result = handler.services.bridge_auth_store.poll_enrollment(
            str(payload.get("device_code") or payload.get("deviceCode") or ""),
            str(payload.get("verifier") or ""),
        )
        status = HTTPStatus.ACCEPTED if result.get("status") == "authorization_pending" else HTTPStatus.OK
        handler._send_json(result, status)
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_bindings_get(handler: Any, query: str) -> None:
    del query
    try:
        _require_explicit_browser_session(handler)
        context = handler._request_context()
        handler._send_json({"bindings": handler.services.bridge_auth_store.list_bindings(context.tenant_id, context.user_id)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_binding_revoke(handler: Any) -> None:
    try:
        _require_explicit_browser_session(handler)
        payload = handler._read_json(max_bytes=16 * 1024)
        context = handler._request_context(payload)
        binding_id = str(payload.get("binding_id") or payload.get("bindingId") or "").strip()
        if not binding_id:
            raise ValueError("bridge_binding_id_required")
        revoked = handler.services.bridge_auth_store.revoke_binding(binding_id, context.tenant_id, context.user_id)
        if not revoked:
            raise KeyError("bridge_binding_not_found")
        handler.services.audit_store.write(
            context.tenant_id,
            context.user_id,
            "bridge.binding.revoked",
            "bridge_binding",
            binding_id,
            {},
            handler.client_address[0] if handler.client_address else "",
        )
        handler._send_json({"revoked": True, "binding_id": binding_id})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _require_explicit_browser_session(handler: Any) -> None:
    cookie = SimpleCookie()
    cookie.load(str(handler.headers.get("Cookie") or ""))
    authorization = str(handler.headers.get("Authorization") or "").strip()
    if "sda_session" not in cookie and not authorization.lower().startswith("bearer "):
        raise AuthenticationError("bridge_approval_login_required")


def _send_approval_page(handler: Any, user_code: str, preview: dict[str, Any]) -> None:
    channel_label = {"workbuddy": "WorkBuddy", "codex": "Codex", "qwork": "QWork"}.get(str(preview.get("channel") or ""), "Bridge")
    safe_channel = escape(channel_label)
    safe_device = escape(str(preview.get("device_name") or ""))
    safe_code = escape(user_code)
    encoded_code = json.dumps(user_code, ensure_ascii=False).replace("<", "\\u003c")
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>授权 {safe_channel} 连接</title>
<style>
body{{margin:0;background:#f6f7f9;color:#17181a;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.card{{max-width:520px;margin:10vh auto;padding:32px;background:#fff;border:1px solid #e7e8eb;border-radius:18px;box-shadow:0 16px 50px rgba(0,0,0,.06)}}
h1{{font-size:22px;margin:0 0 10px}} .meta{{background:#f7f7f8;border-radius:10px;padding:14px 16px;margin:20px 0}}
.label{{color:#777;font-size:13px}} .value{{font-weight:650}} button{{width:100%;border:0;border-radius:10px;padding:12px;background:#111;color:#fff;font-weight:650;cursor:pointer}}
button:disabled{{opacity:.55;cursor:default}} #status{{margin-top:14px;min-height:24px;color:#555}}
</style></head><body><main class="card">
<h1>授权 {safe_channel} 连接 Smart Data Agent</h1>
<p>点击一次后，此设备只能读取你在 SDA 中明确设为“可分享”的原始表，并可回传报告及待复核分析材料。</p>
<div class="meta"><div class="label">设备</div><div class="value">{safe_device}</div><div class="label">授权码</div><div class="value">{safe_code}</div></div>
<button id="approve" type="button">允许连接</button><div id="status" role="status"></div>
</main><script>
const button=document.getElementById('approve'),statusNode=document.getElementById('status');
button.addEventListener('click',async()=>{{button.disabled=true;statusNode.textContent='正在授权…';
try{{const response=await fetch('/api/integrations/bridge/enrollment/approve',{{method:'POST',credentials:'include',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{user_code:{encoded_code}}})}});const payload=await response.json();
if(!response.ok)throw new Error(payload.message||payload.error||'授权失败');statusNode.textContent='授权成功，可以关闭此页面。';button.textContent='已授权';}}
catch(error){{statusNode.textContent=error.message==='bridge_approval_login_required'?'请先在 Smart Data Agent 登录，再刷新此页面。':String(error.message||error);button.disabled=false;}}}});
</script></body></html>"""
    handler._send_bytes(html.encode("utf-8"), content_type="text/html; charset=utf-8")

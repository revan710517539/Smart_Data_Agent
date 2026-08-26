from __future__ import annotations

import unittest
import http.client
import json
import threading
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from urllib.parse import quote

from backend.platform.database import apply_migrations
from backend.authz import normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.server import create_server
from backend.platform.tenancy.governance import (
    InMemoryTenantGovernanceStore,
    SQLiteTenantGovernanceStore,
    TenantScopeService,
)


FINGERPRINT = "a" * 64


class _Enforcer:
    def enforce(self, user_id: str, tenant_id: str, resource: str, action: str) -> bool:
        return user_id == "u_recipient" and tenant_id == "tenant:b" and resource == "asset:*" and action == "read"


class _Assets:
    def list_published_bundle(self, tenant_id: str) -> dict:
        del tenant_id
        return {
            "analysis_skills": [
                {"id": "scene-analysis-intent", "category": "场景", "enabled": True},
                {"id": "topic-descriptive", "category": "主题", "enabled": True},
                {"id": "topic-attribution", "category": "主题", "enabled": True},
                {"id": "topic-predictive", "category": "主题", "enabled": True},
            ]
        }


class _Catalog:
    catalog_ready = True

    def table_assets(self) -> list[dict]:
        return [
            {
                "sourceKey": "loan_table",
                "schemaFingerprint": FINGERPRINT,
                "fields": [
                    {"fieldNameEn": "branch_name"},
                    {"fieldNameEn": "loan_amount"},
                    {"fieldNameEn": "customer_name"},
                ],
            }
        ]


class _RawSource:
    def for_tenant(self, tenant_id: str) -> _Catalog:
        del tenant_id
        return _Catalog()


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


class TenantScopeGovernanceTest(unittest.TestCase):
    def _service(self, store=None) -> TenantScopeService:
        return TenantScopeService(store or InMemoryTenantGovernanceStore(), _Enforcer(), _Assets(), _RawSource())

    def test_invalid_explicit_session_tenant_fails_closed(self) -> None:
        from backend.platform.access.service import AccessControlService

        with self.assertRaisesRegex(PermissionError, "session_tenant_not_authorized"):
            AccessControlService._select_session_tenant(["华兴银行"], "广州银行")
        self.assertEqual(AccessControlService._select_session_tenant(["华兴银行"], None), "tenant:华兴银行")

    def test_topic_assignment_filters_runtime_and_revocation_does_not_restore_defaults(self) -> None:
        service = self._service()
        active = {"tenant:a", "tenant:b"}
        saved = service.assign_topic(
            actor_user_id="u_admin",
            tenant_id="tenant:a",
            topic_skill_id="topic-descriptive",
            active_tenant_ids=active,
        )
        skills = _Assets().list_published_bundle("tenant:a")["analysis_skills"]
        filtered = service.filter_analysis_skills("tenant:a", skills)
        self.assertEqual(
            [item["id"] for item in filtered],
            ["scene-analysis-intent", "topic-descriptive"],
        )

        revoked = service.revoke_topic(saved["assignment_id"], "u_admin", "机构主题调整")
        self.assertEqual(revoked["status"], "revoked")
        self.assertEqual(
            [item["id"] for item in service.filter_analysis_skills("tenant:a", skills)],
            ["scene-analysis-intent"],
        )
        with self.assertRaisesRegex(ValueError, "tenant_topic_skill_not_published"):
            service.assign_topic(
                actor_user_id="u_admin",
                tenant_id="tenant:a",
                topic_skill_id="topic-invented",
                active_tenant_ids=active,
            )

    def test_topic_expiry_fails_closed(self) -> None:
        store = InMemoryTenantGovernanceStore()
        service = self._service(store)
        saved = service.assign_topic(
            actor_user_id="u_admin",
            tenant_id="tenant:a",
            topic_skill_id="topic-attribution",
            active_tenant_ids={"tenant:a"},
            expires_at=_iso(timedelta(minutes=5)),
        )
        store.upsert_topic_assignment({**saved, "expires_at": _iso(timedelta(minutes=-1))})
        filtered = service.filter_analysis_skills(
            "tenant:a", _Assets().list_published_bundle("tenant:a")["analysis_skills"]
        )
        self.assertEqual([item["id"] for item in filtered], ["scene-analysis-intent"])

    def test_cross_tenant_grant_is_exact_bounded_and_revocable(self) -> None:
        service = self._service()
        active = {"tenant:a", "tenant:b"}
        grant = service.create_resource_grant(
            actor_user_id="u_admin",
            source_tenant_id="tenant:a",
            recipient_tenant_id="tenant:b",
            resource_type="raw_table",
            resource_key="loan_table",
            actions=["read"],
            field_scope=["branch_name", "loan_amount"],
            schema_fingerprint=FINGERPRINT,
            purpose="跨机构经营对标",
            active_tenant_ids=active,
            expires_at=_iso(timedelta(days=7)),
        )
        allowed = service.resolve_resource_access(
            user_id="u_recipient",
            recipient_tenant_id="tenant:b",
            source_tenant_id="tenant:a",
            active_tenant_ids=active,
            direct_source_tenant_ids={"tenant:b"},
            resource_type="raw_table",
            resource_key="loan_table",
            action="read",
            schema_fingerprint=FINGERPRINT,
            requested_fields={"branch_name", "loan_amount"},
        )
        self.assertTrue(allowed.allowed)
        self.assertFalse(allowed.direct)
        self.assertEqual(allowed.field_scope, ("branch_name", "loan_amount"))
        self.assertEqual(allowed.grant_ids, (grant["grant_id"],))

        common = dict(
            user_id="u_recipient",
            recipient_tenant_id="tenant:b",
            source_tenant_id="tenant:a",
            active_tenant_ids=active,
            direct_source_tenant_ids={"tenant:b"},
            resource_type="raw_table",
            action="read",
        )
        self.assertFalse(service.resolve_resource_access(**common, resource_key="other", schema_fingerprint=FINGERPRINT).allowed)
        self.assertFalse(service.resolve_resource_access(**common, resource_key="loan_table", schema_fingerprint="b" * 64).allowed)
        self.assertFalse(
            service.resolve_resource_access(
                **common,
                resource_key="loan_table",
                schema_fingerprint=FINGERPRINT,
                requested_fields={"customer_name"},
            ).allowed
        )
        self.assertFalse(
            service.resolve_resource_access(
                **{**common, "active_tenant_ids": {"tenant:b"}},
                resource_key="loan_table",
                schema_fingerprint=FINGERPRINT,
            ).allowed
        )
        service.revoke_resource_grant(grant["grant_id"], "u_admin", "共享到期前终止")
        self.assertFalse(
            service.resolve_resource_access(**common, resource_key="loan_table", schema_fingerprint=FINGERPRINT).allowed
        )

    def test_grant_creation_rejects_unbounded_or_stale_resources(self) -> None:
        service = self._service()
        common = dict(
            actor_user_id="u_admin",
            source_tenant_id="tenant:a",
            recipient_tenant_id="tenant:b",
            resource_type="raw_table",
            actions=["read"],
            field_scope=["loan_amount"],
            schema_fingerprint=FINGERPRINT,
            purpose="经营分析",
            active_tenant_ids={"tenant:a", "tenant:b"},
            expires_at=_iso(timedelta(days=1)),
        )
        with self.assertRaisesRegex(ValueError, "cross_tenant_resource_wildcard_forbidden"):
            service.create_resource_grant(**common, resource_key="*")
        with self.assertRaisesRegex(ValueError, "cross_tenant_raw_table_not_found"):
            service.create_resource_grant(**common, resource_key="missing")
        with self.assertRaisesRegex(ValueError, "cross_tenant_schema_fingerprint_changed"):
            service.create_resource_grant(**{**common, "schema_fingerprint": "b" * 64}, resource_key="loan_table")
        with self.assertRaisesRegex(ValueError, "cross_tenant_field_scope_invalid"):
            service.create_resource_grant(**{**common, "field_scope": ["unknown"]}, resource_key="loan_table")

    def test_tenant_lifecycle_revokes_topics_and_both_grant_directions(self) -> None:
        service = self._service()
        active = {"tenant:a", "tenant:b"}
        service.assign_topic(
            actor_user_id="u_admin",
            tenant_id="tenant:a",
            topic_skill_id="topic-descriptive",
            active_tenant_ids=active,
        )
        for source, recipient in (("tenant:a", "tenant:b"), ("tenant:b", "tenant:a")):
            service.create_resource_grant(
                actor_user_id="u_admin",
                source_tenant_id=source,
                recipient_tenant_id=recipient,
                resource_type="raw_table",
                resource_key="loan_table",
                actions=["read"],
                field_scope=["loan_amount"],
                schema_fingerprint=FINGERPRINT,
                purpose="机构生命周期测试",
                active_tenant_ids=active,
                expires_at=_iso(timedelta(days=1)),
            )

        result = service.revoke_tenant_scope("tenant:a", "u_admin", "tenant_closed")

        self.assertEqual(result, {"topic_assignments_revoked": 1, "resource_grants_revoked": 2})
        self.assertEqual(service.snapshot("tenant:a")["topic_assignments"][0]["status"], "revoked")
        self.assertTrue(
            all(item["status"] == "revoked" for item in service.store.list_resource_grants(include_inactive=True))
        )

    def test_future_grant_is_not_active_and_sqlite_records_survive_reopen(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/scope.sqlite"
            apply_migrations(db_path)
            store = SQLiteTenantGovernanceStore(db_path)
            service = self._service(store)
            assignment = service.assign_topic(
                actor_user_id="u_admin",
                tenant_id="tenant:a",
                topic_skill_id="topic-predictive",
                active_tenant_ids={"tenant:a", "tenant:b"},
            )
            grant = service.create_resource_grant(
                actor_user_id="u_admin",
                source_tenant_id="tenant:a",
                recipient_tenant_id="tenant:b",
                resource_type="raw_table",
                resource_key="loan_table",
                actions=["read"],
                field_scope=["loan_amount"],
                schema_fingerprint=FINGERPRINT,
                purpose="计划生效的分析共享",
                active_tenant_ids={"tenant:a", "tenant:b"},
                effective_at=_iso(timedelta(hours=1)),
                expires_at=_iso(timedelta(days=1)),
            )
            self.assertFalse(
                service.resolve_resource_access(
                    user_id="u_recipient",
                    recipient_tenant_id="tenant:b",
                    source_tenant_id="tenant:a",
                    active_tenant_ids={"tenant:a", "tenant:b"},
                    direct_source_tenant_ids={"tenant:b"},
                    resource_type="raw_table",
                    resource_key="loan_table",
                    action="read",
                    schema_fingerprint=FINGERPRINT,
                ).allowed
            )
            service.close()

            reopened = self._service(SQLiteTenantGovernanceStore(db_path))
            snapshot = reopened.snapshot("tenant:a")
            self.assertEqual(snapshot["topic_assignments"][0]["assignment_id"], assignment["assignment_id"])
            self.assertEqual(snapshot["outgoing_grants"][0]["grant_id"], grant["grant_id"])
            reopened.close()

    def test_http_governance_is_super_admin_only_and_topic_revocation_is_readable(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            server.services.tenant_scope_service.raw_table_source = _RawSource()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            tenant_id = normalize_tenant_id(OPERATING_TENANTS[0])
            recipient_tenant_id = normalize_tenant_id(OPERATING_TENANTS[1])
            try:
                port = server.server_address[1]
                payload = {
                    "kind": "topic_assignment",
                    "tenant_id": tenant_id,
                    "topic_skill_id": "topic-descriptive",
                }
                forbidden_status, _ = self._http_request(
                    port, "POST", "/api/tenant-governance", "u_reviewer", "tenant_demo", payload
                )
                created_status, created = self._http_request(
                    port, "POST", "/api/tenant-governance", "u_super_admin", "tenant_demo", payload
                )
                listed_status, listed = self._http_request(
                    port,
                    "GET",
                    f"/api/tenant-governance?tenant_id={quote(tenant_id)}",
                    "u_super_admin",
                    "tenant_demo",
                )
                assignment_id = created["assignment"]["assignment_id"]
                revoked_status, revoked = self._http_request(
                    port,
                    "DELETE",
                    f"/api/tenant-governance?kind=topic_assignment&assignment_id={assignment_id}&reason=test",
                    "u_super_admin",
                    "tenant_demo",
                )
                grant_status, grant_payload = self._http_request(
                    port,
                    "POST",
                    "/api/tenant-governance",
                    "u_super_admin",
                    "tenant_demo",
                    {
                        "kind": "resource_grant",
                        "source_tenant_id": tenant_id,
                        "recipient_tenant_id": recipient_tenant_id,
                        "resource_type": "raw_table",
                        "resource_key": "loan_table",
                        "actions": ["read"],
                        "field_scope": ["branch_name", "loan_amount"],
                        "schema_fingerprint": FINGERPRINT,
                        "purpose": "机构经营对标",
                        "expires_at": _iso(timedelta(days=7)),
                    },
                )
                grant_id = grant_payload["grant"]["grant_id"]
                revoke_grant_status, revoke_grant_payload = self._http_request(
                    port,
                    "DELETE",
                    f"/api/tenant-governance?kind=resource_grant&grant_id={grant_id}&reason=test",
                    "u_super_admin",
                    "tenant_demo",
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(forbidden_status, 403)
        self.assertEqual(created_status, 201)
        self.assertEqual(created["assignment"]["topic_skill_id"], "topic-descriptive")
        self.assertEqual(listed_status, 200)
        self.assertEqual(listed["topic_assignments"][0]["assignment_id"], assignment_id)
        self.assertEqual(revoked_status, 200)
        self.assertTrue(revoked["revoked"])
        self.assertEqual(revoked["assignment"]["status"], "revoked")
        self.assertEqual(grant_status, 201)
        self.assertEqual(grant_payload["grant"]["resource_key"], "loan_table")
        self.assertEqual(revoke_grant_status, 200)
        self.assertTrue(revoke_grant_payload["revoked"])
        self.assertEqual(revoke_grant_payload["grant"]["status"], "revoked")

    @staticmethod
    def _http_request(
        port: int,
        method: str,
        path: str,
        user_id: str,
        tenant_id: str,
        payload: dict | None = None,
    ) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"X-User-Id": user_id, "X-Tenant-Id": tenant_id}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        connection.close()
        return response.status, json.loads(raw) if raw else {}


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import http.client
import json
import threading
import unittest
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import quote

from backend.authz import InMemoryPolicyRepository, build_default_rbac_seed, normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.routes.tenants import _active_tenants
from backend.platform.api.server import create_server
from backend.platform.tenancy.catalog import create_tenant, delete_tenant, list_active_tenants, update_tenant


class _Cursor:
    def __init__(self, rows: list[object], error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.params: tuple[str, ...] | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, statement: str, params: tuple[str, ...]) -> None:
        if self.error is not None:
            raise self.error
        self.params = params

    def fetchall(self) -> list[object]:
        return self.rows


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _Cursor:
        return self._cursor


class _Pool:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    @contextmanager
    def connection(self):
        yield _Connection(self._cursor)


class TenantRouteTest(unittest.TestCase):
    def test_local_runtime_keeps_source_controlled_operating_catalog(self) -> None:
        handler = SimpleNamespace(services=SimpleNamespace(primary_database_pool=None))

        tenants = _active_tenants(handler)

        self.assertEqual(len(tenants), len(OPERATING_TENANTS))
        self.assertEqual(tenants[0]["id"], normalize_tenant_id(OPERATING_TENANTS[0]))

    def test_relational_runtime_lists_only_provisioned_active_tenants(self) -> None:
        cursor = _Cursor(
            [
                {
                    "tenant_code": "tenant:sda-internal",
                    "tenant_name": "SDA 内部环境",
                    "status": "active",
                },
                ("tenant:华兴银行", "华兴银行", "active"),
            ]
        )
        handler = SimpleNamespace(services=SimpleNamespace(primary_database_pool=_Pool(cursor)))

        tenants = _active_tenants(handler)

        self.assertEqual(
            tenants,
            [
                {"id": "tenant:华兴银行", "name": "华兴银行", "status": "active"},
            ],
        )
        self.assertEqual(cursor.params, ("__global__", "tenant:sda-internal"))

    def test_relational_runtime_hides_virtual_account_and_system_scopes(self) -> None:
        cursor = _Cursor(
            [
                ("account:u_super_admin", "u_super_admin", "active"),
                ("system:default-model-template", "system:default-model-template", "active"),
                ("tenant_demo", "tenant_demo", "active"),
                ("tenant:兰州银行", "兰州银行", "active"),
            ]
        )
        handler = SimpleNamespace(services=SimpleNamespace(primary_database_pool=_Pool(cursor)))

        tenants = _active_tenants(handler)

        self.assertEqual(
            tenants,
            [{"id": "tenant:兰州银行", "name": "兰州银行", "status": "active"}],
        )

    def test_relational_catalog_failure_does_not_fall_back_to_static_tenants(self) -> None:
        handler = SimpleNamespace(
            services=SimpleNamespace(
                primary_database_pool=_Pool(_Cursor([], RuntimeError("tenant_catalog_unavailable")))
            )
        )

        with self.assertRaisesRegex(RuntimeError, "tenant_catalog_unavailable"):
            _active_tenants(handler)

    def test_create_tenant_seeds_admin_and_operator_roles(self) -> None:
        seed = build_default_rbac_seed()
        repository = InMemoryPolicyRepository(
            list(seed.roles),
            list(seed.assignments),
            list(seed.policies),
            seed.manageable_roles,
        )
        services = SimpleNamespace(
            primary_database_pool=None,
            permission_broker=SimpleNamespace(enforcer=SimpleNamespace(repository=repository)),
        )

        created = create_tenant(services, " 测试银行 ")
        catalog = list_active_tenants(services)
        role_names = {
            role.name
            for role in repository.list_roles(created["id"])
            if role.tenant_id == created["id"]
        }
        renamed = update_tenant(services, created["id"], "测试银行股份")
        closed = delete_tenant(services, created["id"])

        self.assertEqual(created["id"], "tenant:测试银行")
        self.assertEqual(created["name"], "测试银行")
        self.assertIn("测试银行", [item["name"] for item in catalog])
        self.assertEqual(role_names, {"管理员", "操作员"})
        self.assertEqual(renamed["name"], "测试银行股份")
        self.assertEqual(closed["status"], "closed")
        self.assertNotIn("测试银行股份", [item["name"] for item in list_active_tenants(services)])
        self.assertEqual(
            {
                role.name
                for role in repository.list_roles(created["id"])
                if role.tenant_id == created["id"]
            },
            set(),
        )

    def test_http_tenant_crud_is_super_admin_only_and_appears_in_role_policies(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                forbidden_status, _ = self._request(port, "POST", "/api/tenants", "u_reviewer", "tenant_demo", {"name": "越权银行"})
                create_status, created = self._request(port, "POST", "/api/tenants", "u_super_admin", "tenant_demo", {"name": "渤海银行"})
                listed_status, listed = self._request(port, "GET", "/api/tenants", "u_super_admin", "tenant_demo")
                roles_status, roles = self._request(port, "GET", "/api/access/role-policies", "u_super_admin", "tenant_demo")
                rename_status, renamed = self._request(
                    port,
                    "PUT",
                    "/api/tenants",
                    "u_super_admin",
                    "tenant_demo",
                    {"id": created["tenant"]["id"], "name": "渤海银行股份"},
                )
                delete_status, deleted = self._request(
                    port,
                    "DELETE",
                    f"/api/tenants?tenant_id={quote(created['tenant']['id'])}",
                    "u_super_admin",
                    "tenant_demo",
                )
                after_status, after = self._request(port, "GET", "/api/tenants", "u_super_admin", "tenant_demo")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(forbidden_status, 403)
        self.assertEqual(create_status, 200)
        self.assertEqual(created["tenant"]["name"], "渤海银行")
        self.assertEqual(listed_status, 200)
        self.assertIn("渤海银行", [item["name"] for item in listed["tenants"]])
        self.assertEqual(roles_status, 200)
        self.assertIn("渤海银行", [item["institution"] for item in roles["permissions"]])
        admin = next(item for item in roles["permissions"] if item["institution"] == "渤海银行")
        self.assertIn("管理员", [config["name"] for config in admin.get("roleConfigs") or []])
        self.assertIn("操作员", [config["name"] for config in admin.get("roleConfigs") or []])
        self.assertEqual(rename_status, 200)
        self.assertEqual(renamed["tenant"]["name"], "渤海银行股份")
        self.assertEqual(delete_status, 200)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(after_status, 200)
        self.assertNotIn("渤海银行股份", [item["name"] for item in after["tenants"]])
        self.assertNotIn("渤海银行", [item["name"] for item in after["tenants"]])

    @staticmethod
    def _request(port: int, method: str, path: str, user_id: str, tenant_id: str, payload: dict | None = None) -> tuple[int, dict]:
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

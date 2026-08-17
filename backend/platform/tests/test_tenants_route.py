from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from backend.authz import normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.routes.tenants import _active_tenants


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

    def test_relational_catalog_failure_does_not_fall_back_to_static_tenants(self) -> None:
        handler = SimpleNamespace(
            services=SimpleNamespace(
                primary_database_pool=_Pool(_Cursor([], RuntimeError("tenant_catalog_unavailable")))
            )
        )

        with self.assertRaisesRegex(RuntimeError, "tenant_catalog_unavailable"):
            _active_tenants(handler)


if __name__ == "__main__":
    unittest.main()

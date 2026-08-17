from __future__ import annotations

import unittest
from contextlib import contextmanager

from backend.platform.access.postgresql_store import PostgreSQLUserDirectoryStore


class _Cursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statement = ""
        self.params: tuple[str, ...] | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, statement: str, params: tuple[str, ...]) -> None:
        self.statement = statement
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


class TenantScopedUserDirectoryTest(unittest.TestCase):
    def test_relational_profile_department_is_projected_from_requested_tenant(self) -> None:
        cursor = _Cursor(
            [
                {
                    "user_code": "u_super_admin",
                    "display_name": "平台管理员",
                    "email": "admin@example.com",
                    "status": "active",
                    "last_login_at": None,
                    "department": "华兴银行",
                }
            ]
        )
        store = PostgreSQLUserDirectoryStore(_Pool(cursor))  # type: ignore[arg-type]

        profiles = store.list_profiles_for_tenant("tenant:华兴银行")

        self.assertEqual(profiles[0].department, "华兴银行")
        self.assertEqual(cursor.params, ("tenant:华兴银行",))
        self.assertIn("t.tenant_code = %s", cursor.statement)
        self.assertIn("m.membership_status = 'active'", cursor.statement)
        self.assertNotIn("tenant:sda-internal", cursor.statement)


if __name__ == "__main__":
    unittest.main()

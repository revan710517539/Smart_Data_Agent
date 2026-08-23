from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import UserDirectoryStore, UserProfile


class PostgreSQLUserDirectoryStore(UserDirectoryStore):
    """Production user directory over IdP subjects and tenant memberships."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def list_profiles(self) -> list[UserProfile]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(self._profile_select() + " ORDER BY u.external_subject")
            rows = cursor.fetchall()
        return [self._profile_from_row(row) for row in rows]

    def list_profiles_for_tenant(self, tenant_id: str) -> list[UserProfile]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                self._profile_select_for_tenant() + " ORDER BY u.external_subject",
                (tenant_id,),
            )
            rows = cursor.fetchall()
        return [self._profile_from_row(row) for row in rows]

    def get_profile(self, user_id: str) -> UserProfile | None:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(self._profile_select() + " WHERE u.external_subject = %s", (user_id,))
            row = cursor.fetchone()
        return self._profile_from_row(row) if row else None

    def get_profile_by_email(self, email: str) -> UserProfile | None:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(self._profile_select() + " WHERE lower(u.email) = lower(%s)", (email.strip(),))
            row = cursor.fetchone()
        return self._profile_from_row(row) if row else None

    def upsert_profile(self, profile: UserProfile) -> UserProfile:
        status = _storage_status(profile.status)
        logged_in = str(profile.last_login or "").strip() not in {"", "未登录"}
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_user_profiles(
                        external_subject, email, display_name, phone, status, last_login_at
                    ) VALUES (%s, lower(%s), %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END)
                    ON CONFLICT(external_subject) DO UPDATE SET
                        email = EXCLUDED.email,
                        display_name = EXCLUDED.display_name,
                        phone = EXCLUDED.phone,
                        status = EXCLUDED.status,
                        last_login_at = CASE WHEN %s THEN now() ELSE platform_user_profiles.last_login_at END,
                        updated_at = now(),
                        lock_version = platform_user_profiles.lock_version + 1
                    """,
                    (
                        profile.user_id,
                        profile.email,
                        profile.name,
                        _pending_org_phone(profile),
                        status,
                        logged_in,
                        logged_in,
                    ),
                )
            user_key = PostgreSQLIdentityResolver.user_id(connection, profile.user_id, required=False)
            department = str(profile.department or "").strip()
            if user_key is not None and department and department != "未分配部门":
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE platform_user_tenant_memberships m
                        SET org_unit_id = (
                            SELECT o.org_unit_id
                            FROM platform_org_units o
                            WHERE o.tenant_id = m.tenant_id
                              AND o.org_name = %s AND o.status = 'active'
                            ORDER BY o.path LIMIT 1
                        )
                        WHERE m.user_id = %s AND m.membership_status = 'active'
                          AND EXISTS (
                              SELECT 1
                              FROM platform_org_units o
                              WHERE o.tenant_id = m.tenant_id
                                AND o.org_name = %s AND o.status = 'active'
                          )
                        """,
                        (department, user_key, department),
                    )
        saved = UserProfile(
            user_id=profile.user_id,
            name=profile.name,
            department=profile.department,
            email=profile.email.lower(),
            status=_ui_status(status),
            last_login=profile.last_login,
        )
        if self.get_password_hash(saved.user_id) is None:
            from .passwords import default_password_hash

            self.set_password_hash(saved.user_id, default_password_hash())
        return saved

    def delete_profile(self, user_id: str) -> bool:
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform_user_profiles
                SET status = 'disabled', updated_at = now(), lock_version = lock_version + 1
                WHERE external_subject = %s AND status <> 'disabled'
                """,
                (user_id,),
            )
            return cursor.rowcount > 0

    def get_password_hash(self, user_id: str) -> str | None:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.password_hash
                FROM platform_user_credentials c
                JOIN platform_user_profiles u ON u.user_id = c.user_id
                WHERE u.external_subject = %s
                """,
                (str(user_id or "").strip(),),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        hashed = str(_value(row, "password_hash", 0) or "").strip()
        return hashed or None

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        key = str(user_id or "").strip()
        digest = str(password_hash or "").strip()
        if not key or not digest:
            raise ValueError("password_hash_required")
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT user_id FROM platform_user_profiles WHERE external_subject = %s",
                (key,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError("user_not_provisioned")
            internal_id = _value(row, "user_id", 0)
            cursor.execute(
                "SELECT 1 FROM platform_user_credentials WHERE user_id = %s",
                (internal_id,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    "INSERT INTO platform_user_credentials(user_id, password_hash) VALUES (%s, %s)",
                    (internal_id, digest),
                )
            else:
                cursor.execute(
                    """
                    UPDATE platform_user_credentials
                    SET password_hash = %s, password_updated_at = now(), updated_at = now()
                    WHERE user_id = %s
                    """,
                    (digest, internal_id),
                )

    @staticmethod
    def _profile_select() -> str:
        return """
            SELECT u.external_subject AS user_code, u.display_name, u.email, u.status,
                   u.last_login_at, u.phone,
                   COALESCE((
                       SELECT o.org_name
                       FROM platform_user_tenant_memberships m
                       LEFT JOIN platform_org_units o ON o.org_unit_id = m.org_unit_id
                       WHERE m.user_id = u.user_id AND m.membership_status = 'active'
                       ORDER BY (m.joined_at IS NULL), m.joined_at, m.created_at, m.membership_id
                       LIMIT 1
                   ), '未分配部门') AS department
            FROM platform_user_profiles u
        """

    @staticmethod
    def _profile_select_for_tenant() -> str:
        return """
            SELECT u.external_subject AS user_code, u.display_name, u.email, u.status,
                   u.last_login_at, u.phone,
                   COALESCE((
                       SELECT o.org_name
                       FROM platform_user_tenant_memberships m
                       JOIN platform_tenants t ON t.tenant_id = m.tenant_id
                       LEFT JOIN platform_org_units o
                         ON o.org_unit_id = m.org_unit_id AND o.status = 'active'
                       WHERE m.user_id = u.user_id
                         AND m.membership_status = 'active'
                         AND t.status = 'active'
                         AND t.tenant_code = %s
                       ORDER BY (m.joined_at IS NULL), m.joined_at, m.created_at, m.membership_id
                       LIMIT 1
                   ), '未分配部门') AS department
            FROM platform_user_profiles u
        """

    @staticmethod
    def _profile_from_row(row: Any) -> UserProfile:
        last_login = _value(row, "last_login_at", 4)
        last_login_text = last_login.isoformat() if isinstance(last_login, datetime) else str(last_login or "未登录")
        phone = str(_value(row, "phone", 5) or "")
        department = str(_value(row, "department", 6) or "未分配部门")
        if phone.startswith("org:") and (department in {"", "未分配部门"} or str(_value(row, "status", 3)) == "invited"):
            department = phone[4:]
        return UserProfile(
            user_id=str(_value(row, "user_code", 0)),
            name=str(_value(row, "display_name", 1)),
            email=str(_value(row, "email", 2)),
            status=_ui_status(str(_value(row, "status", 3))),
            last_login=last_login_text,
            department=department,
        )

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


_STORAGE_STATUS = {
    "active": "active",
    "invited": "invited",
    "locked": "locked",
    "disabled": "disabled",
    "inactive": "disabled",
}


def _storage_status(value: str) -> str:
    return _STORAGE_STATUS.get(str(value or "").strip(), "active")


def _ui_status(value: str) -> str:
    return "inactive" if str(value or "").strip() in {"disabled", "inactive", "locked"} else str(value or "active")


def _pending_org_phone(profile: UserProfile) -> str | None:
    if str(profile.status or "") == "invited":
        institution = str(profile.department or "").strip()
        if institution and institution != "未分配部门":
            return f"org:{institution}"[:64]
    return None


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]

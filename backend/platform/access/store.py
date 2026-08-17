from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from backend.platform.storage import connect_sqlite
from typing import Protocol


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    name: str
    department: str
    email: str
    status: str = "active"
    last_login: str = "未登录"


class UserDirectoryStore(Protocol):
    def list_profiles(self) -> list[UserProfile]:
        ...

    def get_profile(self, user_id: str) -> UserProfile | None:
        ...

    def get_profile_by_email(self, email: str) -> UserProfile | None:
        ...

    def upsert_profile(self, profile: UserProfile) -> UserProfile:
        ...

    def delete_profile(self, user_id: str) -> bool:
        ...


class InMemoryUserDirectoryStore:
    def __init__(self, profiles: list[UserProfile] | None = None) -> None:
        self._profiles = {profile.user_id: profile for profile in profiles or []}

    def list_profiles(self) -> list[UserProfile]:
        return sorted(self._profiles.values(), key=lambda profile: profile.user_id)

    def get_profile(self, user_id: str) -> UserProfile | None:
        return self._profiles.get(user_id)

    def get_profile_by_email(self, email: str) -> UserProfile | None:
        normalized = email.strip().lower()
        for profile in self._profiles.values():
            if profile.email.lower() == normalized:
                return profile
        return None

    def upsert_profile(self, profile: UserProfile) -> UserProfile:
        self._profiles[profile.user_id] = profile
        return profile

    def delete_profile(self, user_id: str) -> bool:
        return self._profiles.pop(user_id, None) is not None


class SQLiteUserDirectoryStore:
    def __init__(self, db_path: str | Path, profiles: list[UserProfile] | None = None, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()
        for profile in profiles or []:
            self.seed_profile(profile)

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS platform_user_profiles (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                last_login TEXT NOT NULL DEFAULT '未登录',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_user_profiles_email
                ON platform_user_profiles(lower(email));
            """
        )
        self._conn.commit()

    def seed_profile(self, profile: UserProfile) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_user_profiles(
                    user_id, name, department, email, status, last_login
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.user_id,
                    profile.name,
                    profile.department,
                    profile.email,
                    profile.status,
                    profile.last_login,
                ),
            )

    def list_profiles(self) -> list[UserProfile]:
        rows = self._conn.execute(
            """
            SELECT user_id, name, department, email, status, last_login
            FROM platform_user_profiles
            ORDER BY user_id
            """
        ).fetchall()
        return [self._profile_from_row(row) for row in rows]

    def get_profile(self, user_id: str) -> UserProfile | None:
        row = self._conn.execute(
            """
            SELECT user_id, name, department, email, status, last_login
            FROM platform_user_profiles
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        return self._profile_from_row(row) if row else None

    def get_profile_by_email(self, email: str) -> UserProfile | None:
        row = self._conn.execute(
            """
            SELECT user_id, name, department, email, status, last_login
            FROM platform_user_profiles
            WHERE lower(email) = lower(?)
            """,
            (email.strip(),),
        ).fetchone()
        return self._profile_from_row(row) if row else None

    def upsert_profile(self, profile: UserProfile) -> UserProfile:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_user_profiles(
                    user_id, name, department, email, status, last_login, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = excluded.name,
                    department = excluded.department,
                    email = excluded.email,
                    status = excluded.status,
                    last_login = excluded.last_login,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    profile.user_id,
                    profile.name,
                    profile.department,
                    profile.email,
                    profile.status,
                    profile.last_login,
                ),
            )
        return profile

    def delete_profile(self, user_id: str) -> bool:
        with self._conn:
            cursor = self._conn.execute("DELETE FROM platform_user_profiles WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> UserProfile:
        return UserProfile(
            user_id=row["user_id"],
            name=row["name"],
            department=row["department"],
            email=row["email"],
            status=row["status"],
            last_login=row["last_login"],
        )


def default_user_profiles() -> list[UserProfile]:
    return [
        UserProfile("u_super_admin", "胥京波", "平台管理中心", "xujingbo-jk@qifu.com", "active", "今日 09:15"),
        UserProfile("u_reviewer", "平台复核员", "经营分析中心", "reviewer@smart-data-agent.local", "active", "今日 09:20"),
        UserProfile("u_lina", "李娜", "华兴银行", "lina@bank.com", "active", "今日 08:42"),
        UserProfile("u_wangqiang", "王强", "广州银行", "wangqiang@bank.com", "active", "昨日 17:30"),
        UserProfile("u_zhaomin", "赵敏", "郑州银行", "zhaomin@bank.com", "active", "昨日 15:20"),
        UserProfile("u_liuyang", "刘洋", "南京银行", "liuyang@bank.com", "inactive", "1周前"),
        UserProfile("u_chenlei", "陈磊", "三峡银行", "chenlei@bank.com", "active", "今日 09:30"),
    ]

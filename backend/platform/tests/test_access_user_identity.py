from __future__ import annotations

import unittest
from http import HTTPStatus
from types import SimpleNamespace

from backend.authz import normalize_tenant_id
from backend.platform.access.service import (
    _allocate_user_id,
    _raise_profile_constraint_error,
    _user_id_from_email,
)
from backend.platform.access.store import InMemoryUserDirectoryStore, UserProfile
from backend.platform.api.support import send_route_exception
from backend.platform.bootstrap import build_local_platform
from backend.platform.settings import DEFAULT_RELAY_MODEL_ID, list_models_for_application
from backend.platform.tenancy import ExecutionContext


class AccessUserIdentityTest(unittest.TestCase):
    def test_user_id_from_email_slugifies_local_part(self) -> None:
        self.assertEqual(_user_id_from_email("zhouliang-jk@qifu.com"), "u_zhouliang_jk")

    def test_allocate_user_id_avoids_external_subject_collision(self) -> None:
        store = InMemoryUserDirectoryStore(
            [UserProfile("u_zhouliang_jk", "已有用户", "华兴银行", "other@qifu.com")]
        )
        self.assertEqual(_allocate_user_id(store, "zhouliang-jk@qifu.com"), "u_zhouliang_jk_2")

    def test_unique_violation_is_mapped_to_email_conflict(self) -> None:
        class DuplicateEmail(Exception):
            errno = 1062

        with self.assertRaises(ValueError) as raised:
            _raise_profile_constraint_error(DuplicateEmail("Duplicate entry 'zhouliang-jk@qifu.com' for key 'uq_platform_user_profiles_email'"))
        self.assertIn("用户邮箱已存在", str(raised.exception))

    def test_unique_violation_is_mapped_to_subject_conflict(self) -> None:
        class DuplicateSubject(Exception):
            pgcode = "23505"

        with self.assertRaises(ValueError) as raised:
            _raise_profile_constraint_error(
                DuplicateSubject('duplicate key value violates unique constraint "uq_platform_user_profiles_external_subject"')
            )
        self.assertIn("用户标识已存在", str(raised.exception))

    def test_identity_errors_are_returned_as_chinese_reasons(self) -> None:
        captured: dict[str, object] = {}

        def send_json(payload, status=HTTPStatus.OK, headers=None):
            captured.update(payload=payload, status=status)

        handler = SimpleNamespace(_send_json=send_json, headers={})
        send_route_exception(handler, KeyError("user_not_provisioned"))
        self.assertEqual(captured["status"], HTTPStatus.NOT_FOUND)
        self.assertIn("用户档案", captured["payload"]["message"])

        send_route_exception(handler, ValueError("用户标识已存在，请检查……"))
        self.assertEqual(captured["status"], HTTPStatus.BAD_REQUEST)
        self.assertEqual(captured["payload"]["error"], "access_user_identity_conflict")
        self.assertIn("用户标识已存在", captured["payload"]["message"])

    def test_upsert_user_keeps_roles_from_other_institutions(self) -> None:
        services = build_local_platform()
        try:
            primary = normalize_tenant_id("华兴银行")
            secondary = normalize_tenant_id("广州银行")
            created = services.access_service.upsert_user(
                ExecutionContext(user_id="u_super_admin", tenant_id=primary),
                {
                    "id": "u_multi_keep",
                    "name": "跨机构用户",
                    "email": "multi-keep@bank.com",
                    "status": "active",
                    "department": "华兴银行",
                    "tenantRoles": [
                        {"tenant": "华兴银行", "role": "管理员"},
                        {"tenant": "广州银行", "role": "操作员"},
                    ],
                },
            )
            updated = services.access_service.upsert_user(
                ExecutionContext(user_id="u_super_admin", tenant_id=primary),
                {
                    "id": created["id"],
                    "name": "跨机构用户",
                    "email": "multi-keep@bank.com",
                    "status": "active",
                    "department": "华兴银行",
                    "tenantRoles": [{"tenant": "华兴银行", "role": "操作员"}],
                },
            )
        finally:
            services.close()

        roles = {(item["tenant"], item["role"]) for item in updated["tenantRoles"]}
        self.assertEqual(roles, {("华兴银行", "操作员"), ("广州银行", "操作员")})

    def test_upsert_user_accepts_catalog_tenant_id(self) -> None:
        services = build_local_platform()
        try:
            tenant_id = normalize_tenant_id("华兴银行")
            saved = services.access_service.upsert_user(
                ExecutionContext(user_id="u_super_admin", tenant_id=tenant_id),
                {
                    "name": "目录用户",
                    "email": "catalog-user@bank.com",
                    "status": "active",
                    "department": "华兴银行",
                    "tenantRoles": [{"tenant": "华兴银行", "tenantId": tenant_id, "role": "操作员"}],
                },
            )
        finally:
            services.close()

        self.assertEqual(saved["tenantRoles"][0]["tenant"], "华兴银行")
        self.assertEqual(saved["tenantRoles"][0]["role"], "操作员")

    def test_inactive_user_can_be_created_and_granted(self) -> None:
        services = build_local_platform()
        try:
            tenant_id = normalize_tenant_id("华兴银行")
            saved = services.access_service.upsert_user(
                ExecutionContext(user_id="u_super_admin", tenant_id=tenant_id),
                {
                    "name": "停用用户",
                    "email": "inactive-user@bank.com",
                    "status": "inactive",
                    "department": "华兴银行",
                    "tenantRoles": [{"tenant": "华兴银行", "role": "操作员"}],
                },
            )
        finally:
            services.close()

        self.assertEqual(saved["status"], "inactive")
        self.assertEqual(saved["tenantRoles"][0]["role"], "操作员")

    def test_super_admin_lists_all_authorized_users_and_institution_admin_keeps_local_users(self) -> None:
        services = build_local_platform()
        try:
            huaxing = normalize_tenant_id("华兴银行")
            shizuishan = normalize_tenant_id("石嘴山银行")
            services.access_service.upsert_user(
                ExecutionContext(user_id="u_super_admin", tenant_id=huaxing),
                {
                    "name": "周亮",
                    "email": "zhouliang-list@qifu.com",
                    "status": "active",
                    "department": "石嘴山银行",
                    "tenantRoles": [{"tenant": "石嘴山银行", "role": "操作员"}],
                },
            )
            local_admin = services.access_service.upsert_user(
                ExecutionContext(user_id="u_super_admin", tenant_id=shizuishan),
                {
                    "name": "石嘴山管理员",
                    "email": "shizuishan-admin@bank.com",
                    "status": "active",
                    "department": "石嘴山银行",
                    "tenantRoles": [{"tenant": "石嘴山银行", "role": "管理员"}],
                },
            )
            as_super_on_huaxing = services.access_service.list_users(
                ExecutionContext(user_id="u_super_admin", tenant_id=huaxing)
            )
            zhou = next(item for item in as_super_on_huaxing if item["email"] == "zhouliang-list@qifu.com")
            self.assertEqual({(item["tenant"], item["role"]) for item in zhou["tenantRoles"]}, {("石嘴山银行", "操作员")})
            as_huaxing_admin = services.access_service.list_users(
                ExecutionContext(user_id="u_lina", tenant_id=huaxing)
            )
            self.assertNotIn("zhouliang-list@qifu.com", {item["email"] for item in as_huaxing_admin})
            as_shizuishan_admin = services.access_service.list_users(
                ExecutionContext(user_id=local_admin["id"], tenant_id=shizuishan)
            )
            self.assertIn("zhouliang-list@qifu.com", {item["email"] for item in as_shizuishan_admin})
        finally:
            services.close()

    def test_role_policy_save_keeps_asset_read(self) -> None:
        services = build_local_platform()
        try:
            tenant_id = normalize_tenant_id("华兴银行")
            before = services.permission_broker.enforcer.enforce(
                "u_lina", tenant_id, "asset:*", "read", {"tenant_id": tenant_id}
            )
            services.access_service.save_role_permission(
                ExecutionContext(user_id="u_super_admin", tenant_id=tenant_id),
                {
                    "institution": "华兴银行",
                    "adminMenus": ["经营周报", "系统管理"],
                    "adminDataScopes": ["指标字典"],
                    "operatorAdminMenus": ["经营周报"],
                    "operatorAdminDataScopes": ["指标字典"],
                    "manageableRoles": ["操作员"],
                },
            )
            after = services.permission_broker.enforcer.enforce(
                "u_lina", tenant_id, "asset:*", "read", {"tenant_id": tenant_id}
            )
        finally:
            services.close()

        self.assertTrue(before)
        self.assertTrue(after)

    def test_failed_custom_model_is_not_routable(self) -> None:
        services = build_local_platform()
        try:
            from backend.platform.settings.store import account_system_config_scope

            scope = account_system_config_scope("u_super_admin")
            services.system_config_store.upsert_model(
                scope,
                {
                    "id": "model_custom_failed",
                    "name": "失败模型",
                    "modelName": "中转站",
                    "key": "https://models.example/v1",
                    "value": "secret",
                    "applicationModule": "global_text_model",
                    "availableModels": ["gpt-5.5"],
                    "enabledModels": ["gpt-5.5"],
                    "testStatus": "failed",
                    "status": "draft",
                },
                updated_by="u_super_admin",
            )
            candidates = list_models_for_application(
                services.system_config_store,
                normalize_tenant_id("华兴银行"),
                "intelligent_analysis_reasoning",
                user_id="u_super_admin",
            )
        finally:
            services.close()

        self.assertNotIn("model_custom_failed", {item["id"] for item in candidates})


if __name__ == "__main__":
    unittest.main()

import unittest
from tempfile import TemporaryDirectory

from backend.authz import (
    AuthEnforcer,
    InMemoryPolicyRepository,
    SQLitePolicyRepository,
    assert_single_global_super_admin,
    build_default_rbac_seed,
    expand_menu_selection,
    normalize_tenant_id,
    tenant_role_id,
)
from backend.authz.models import PermissionPolicy, Role, RoleAssignment, RoleLevel


class AuthEnforcerTest(unittest.TestCase):
    def setUp(self) -> None:
        roles = [
            Role("super", None, "超级管理员", RoleLevel.SUPER_ADMIN, True),
            Role("tenant_admin", "tenant_a", "管理员", RoleLevel.TENANT_ADMIN, True),
            Role("operator", "tenant_a", "操作员", RoleLevel.OPERATOR, True),
        ]
        assignments = [
            RoleAssignment("u_super", "*", "super"),
            RoleAssignment("u_admin", "tenant_a", "tenant_admin"),
            RoleAssignment("u_operator", "tenant_a", "operator"),
        ]
        policies = [
            PermissionPolicy("super", "*", "*", "*", attrs={}),
            PermissionPolicy("tenant_admin", "tenant_a", "menu:*", "read"),
            PermissionPolicy("tenant_admin", "tenant_a", "metric:*", "read", attrs={"tenant_id": "tenant_a"}),
            PermissionPolicy(
                "operator",
                "tenant_a",
                "metric:*",
                "read",
                attrs={
                    "tenant_id": "tenant_a",
                    "resource_type": "metric",
                    "metric_ids": ["m_balance", "m_loan"],
                    "fields": ["branch_id", "metric_value"],
                    "row_filter": {"tenant_id": "tenant_a"},
                },
            ),
        ]
        self.enforcer = AuthEnforcer(
            InMemoryPolicyRepository(
                roles=roles,
                assignments=assignments,
                policies=policies,
                manageable_roles={"tenant_admin": {"operator"}},
            )
        )

    def test_super_admin_cross_tenant(self) -> None:
        self.assertTrue(self.enforcer.enforce("u_super", "tenant_b", "metric:any", "delete"))

    def test_super_admin_overrides_lower_role_deny(self) -> None:
        repository = InMemoryPolicyRepository(
            roles=[
                Role("super", None, "超级管理员", RoleLevel.SUPER_ADMIN, True),
                Role("operator", "tenant_a", "操作员", RoleLevel.OPERATOR, True),
            ],
            assignments=[
                RoleAssignment("u_mixed", "*", "super"),
                RoleAssignment("u_mixed", "tenant_a", "operator"),
            ],
            policies=[
                PermissionPolicy("super", "*", "*", "*", priority=0),
                PermissionPolicy("operator", "tenant_a", "metric:*", "delete", effect="deny", priority=10),
            ],
        )
        enforcer = AuthEnforcer(repository)

        self.assertTrue(enforcer.enforce("u_mixed", "tenant_a", "metric:any", "delete"))

    def test_tenant_domain_isolation(self) -> None:
        self.assertTrue(self.enforcer.enforce("u_admin", "tenant_a", "menu:weekly-report", "read"))
        self.assertFalse(self.enforcer.enforce("u_admin", "tenant_b", "menu:weekly-report", "read"))

    def test_metric_abac_fields_and_rows(self) -> None:
        self.assertTrue(
            self.enforcer.enforce(
                "u_operator",
                "tenant_a",
                "metric:*",
                "read",
                {
                    "tenant_id": "tenant_a",
                    "resource_type": "metric",
                    "metric_ids": {"m_balance"},
                    "fields": {"branch_id", "metric_value"},
                },
            )
        )
        self.assertFalse(
            self.enforcer.enforce(
                "u_operator",
                "tenant_a",
                "metric:*",
                "read",
                {
                    "tenant_id": "tenant_a",
                    "resource_type": "metric",
                    "metric_ids": {"m_balance"},
                    "fields": {"branch_id", "customer_mobile"},
                },
            )
        )

    def test_manageable_role_boundary(self) -> None:
        self.assertTrue(self.enforcer.can_manage_role("u_admin", "tenant_a", "operator"))
        self.assertFalse(self.enforcer.can_manage_role("u_operator", "tenant_a", "tenant_admin"))

    def test_default_rbac_has_single_global_super_admin(self) -> None:
        seed = build_default_rbac_seed(["华兴银行", "广州银行"])
        assert_single_global_super_admin(seed.roles)

        super_roles = [role for role in seed.roles if role.name == "超级管理员"]
        self.assertEqual(len(super_roles), 1)
        self.assertTrue(super_roles[0].is_global)
        self.assertFalse(any(role.tenant_id and role.name == "超级管理员" for role in seed.roles))

    def test_default_rbac_role_hierarchy_and_manageable_scope(self) -> None:
        seed = build_default_rbac_seed(["华兴银行"])
        tenant_id = normalize_tenant_id("华兴银行")
        admin_role_id = tenant_role_id(tenant_id, "管理员")
        operator_role_id = tenant_role_id(tenant_id, "操作员")
        repository = InMemoryPolicyRepository(
            roles=list(seed.roles),
            assignments=[
                *seed.assignments,
                RoleAssignment("u_admin_hx", tenant_id, admin_role_id),
                RoleAssignment("u_operator_hx", tenant_id, operator_role_id),
            ],
            policies=list(seed.policies),
            manageable_roles=seed.manageable_roles,
        )
        enforcer = AuthEnforcer(repository)

        self.assertTrue(enforcer.can_manage_role("u_admin_hx", tenant_id, operator_role_id))
        self.assertFalse(enforcer.can_manage_role("u_admin_hx", tenant_id, admin_role_id))
        self.assertTrue(enforcer.can_manage_role("u_super_admin", tenant_id, admin_role_id))
        self.assertTrue(enforcer.enforce("u_super_admin", tenant_id, "metric:any", "delete"))
        self.assertFalse(enforcer.enforce("u_operator_hx", tenant_id, "metric:any", "delete"))

    def test_parent_menu_selection_expands_children(self) -> None:
        expanded = expand_menu_selection(["business-analysis"])

        self.assertIn("business-analysis", expanded)
        self.assertIn("business-analysis.weekly-report", expanded)
        self.assertIn("business-analysis.supervision", expanded)
        self.assertNotIn("business-analysis.funnel", expanded)
        self.assertNotIn("business-analysis.sandbox", expanded)
        self.assertNotIn("business-analysis.email-daily", expanded)

    def test_child_menu_selection_keeps_only_parent_and_child(self) -> None:
        expanded = expand_menu_selection(["business-analysis.weekly-report"])

        self.assertEqual(
            expanded,
            {
                "business-analysis",
                "business-analysis.weekly-report",
            },
        )

    def test_sqlite_policy_repository_matches_enforcer_contract(self) -> None:
        seed = build_default_rbac_seed(["华兴银行"])
        tenant_id = normalize_tenant_id("华兴银行")
        admin_role_id = tenant_role_id(tenant_id, "管理员")
        operator_role_id = tenant_role_id(tenant_id, "操作员")

        with TemporaryDirectory() as tmpdir:
            repository = SQLitePolicyRepository(f"{tmpdir}/authz.sqlite")
            try:
                repository.seed(
                    roles=seed.roles,
                    assignments=[
                        *seed.assignments,
                        RoleAssignment("u_admin_hx", tenant_id, admin_role_id),
                        RoleAssignment("u_operator_hx", tenant_id, operator_role_id),
                    ],
                    policies=seed.policies,
                    manageable_roles=seed.manageable_roles,
                )
                enforcer = AuthEnforcer(repository)

                self.assertTrue(enforcer.enforce("u_admin_hx", tenant_id, "metric:any", "read"))
                self.assertTrue(enforcer.can_manage_role("u_admin_hx", tenant_id, operator_role_id))
                self.assertFalse(enforcer.can_manage_role("u_operator_hx", tenant_id, admin_role_id))
            finally:
                repository.close()

    def test_sqlite_policy_seed_is_idempotent(self) -> None:
        seed = build_default_rbac_seed(["华兴银行"])

        with TemporaryDirectory() as tmpdir:
            repository = SQLitePolicyRepository(f"{tmpdir}/authz.sqlite")
            try:
                repository.seed(seed.roles, seed.assignments, seed.policies, seed.manageable_roles)
                first_policy_count = repository._conn.execute("SELECT COUNT(*) FROM auth_permission_policies").fetchone()[0]

                repository.seed(seed.roles, seed.assignments, seed.policies, seed.manageable_roles)
                second_policy_count = repository._conn.execute("SELECT COUNT(*) FROM auth_permission_policies").fetchone()[0]
            finally:
                repository.close()

            self.assertEqual(second_policy_count, first_policy_count)


if __name__ == "__main__":
    unittest.main()

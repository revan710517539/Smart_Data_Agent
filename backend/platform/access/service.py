from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

from backend.authz import OPERATING_TENANTS, SUPER_ADMIN_ROLE_ID, SUPER_ADMIN_USER_ID, normalize_tenant_id, tenant_role_id
from backend.authz.models import PermissionPolicy, Role, RoleAssignment, RoleLevel
from backend.authz.repository import PolicyRepository
from backend.platform.governance import PermissionBroker
from backend.platform.tenancy import ExecutionContext

from .store import UserDirectoryStore, UserProfile


PERMISSION_MENU_LABELS = [
    "多机构分析",
    "经营分析",
    "经营周报",
    "机构督导",
    "分客群分析",
    "市场洞察",
    "客群分析",
    "竞品分析",
    "自助分析",
    "智能分析",
    "我的报告",
    "任务工作台",
    "待办任务",
    "自动化任务",
    "skill/插件",
    "数据资产",
    "指标字典",
    "知识记忆",
    "站内数据",
    "质量监控",
    "推送与订阅",
    "预警规则",
    "订阅管理",
    "推送记录",
    "系统管理",
    "用户管理",
    "角色权限",
    "审计日志",
    "系统配置",
]
PERMISSION_DATA_SCOPES = [
    "经营指标汇总",
    "机构周报数据",
    "业务漏斗数据",
    "客户画像数据",
    "指标字典",
    "知识记忆",
    "用户行为习惯",
    "原始表",
    "主题表",
    "质量监控",
    "系统配置数据",
]
_MENU_LABEL_TO_KEYS = {
    "多机构分析": {"dashboard"},
    "管理驾驶舱": {"dashboard"},
    "经营分析": {"business-analysis", "business-analysis.weekly-report", "business-analysis.supervision", "business-analysis.customer-segment"},
    "经营周报": {"business-analysis.weekly-report"},
    "机构督导": {"business-analysis.supervision"},
    "分客群分析": {"business-analysis.customer-segment"},
    "市场洞察": {"market-customer", "market-customer.segment", "market-customer.competition"},
    "市场与客户洞察": {"market-customer", "market-customer.segment", "market-customer.competition"},
    "客群分析": {"market-customer.segment"},
    "竞品分析": {"market-customer.competition"},
    "自助分析": {"self-analysis", "self-analysis.visual-reports", "self-analysis.smart-analysis", "self-analysis.my-reports", "self-analysis.analysis-config", "task-workbench.skills"},
    "可视化报表": {"self-analysis.visual-reports"},
    "智能分析": {"self-analysis.smart-analysis"},
    "我的报告": {"self-analysis.my-reports"},
    "我的报表": {"self-analysis.my-reports"},
    "任务工作台": {"task-workbench", "task-workbench.todos", "task-workbench.tasks"},
    "待办任务": {"task-workbench.todos"},
    "自动化任务": {"task-workbench.tasks"},
    "skill/插件": {"task-workbench.skills"},
    "数据资产": {"data-assets", "data-assets.metrics", "data-assets.knowledge", "data-assets.data-management", "data-assets.quality"},
    "指标字典": {"data-assets.metrics"},
    "知识记忆": {"data-assets.knowledge"},
    "站内数据": {"data-assets.data-management"},
    "数据管理": {"data-assets.data-management"},
    "质量监控": {"data-assets.quality"},
    "推送与订阅": {"notifications", "notifications.alerts", "notifications.subscriptions", "notifications.history"},
    "预警规则": {"notifications.alerts"},
    "订阅管理": {"notifications.subscriptions"},
    "推送记录": {"notifications.history"},
    "系统管理": {"settings", "settings.users", "settings.roles", "settings.audit", "settings.config"},
    "用户管理": {"settings.users"},
    "角色权限": {"settings.roles"},
    "审计日志": {"settings.audit"},
    "系统配置": {"settings.config"},
}
_MANDATORY_MENU_KEYS: set[str] = {"settings.audit", "settings.config"}
_SYSTEM_ROLE_NAMES = {"管理员", "操作员"}


class AccessControlService:
    """User directory and RBAC assignment service for the system settings UI."""

    def __init__(
        self,
        user_store: UserDirectoryStore,
        policy_repository: PolicyRepository,
        permission_broker: PermissionBroker,
        tenant_catalog: Callable[[], list[dict[str, str]]] | None = None,
    ) -> None:
        self.user_store = user_store
        self.policy_repository = policy_repository
        self.permission_broker = permission_broker
        self._tenant_catalog = tenant_catalog

    def _active_tenant_catalog(self) -> list[dict[str, str]]:
        if self._tenant_catalog is not None:
            return self._tenant_catalog()
        return [
            {"id": normalize_tenant_id(label), "name": label, "status": "active"}
            for label in _known_tenant_labels(self.policy_repository.list_roles())
        ]

    def _active_tenant_names(self) -> list[str]:
        return [
            str(item.get("name") or "").strip()
            for item in self._active_tenant_catalog()
            if str(item.get("status") or "active") == "active" and str(item.get("name") or "").strip()
        ]

    def _canonical_catalog_tenant(self, value: str) -> dict[str, str] | None:
        hinted = str(value or "").strip()
        if not hinted:
            return None
        canonical_label = _canonical_tenant_label(hinted)
        for item in self._active_tenant_catalog():
            tenant_id = str(item.get("id") or "").strip()
            tenant_name = str(item.get("name") or "").strip()
            status = str(item.get("status") or "active").strip()
            if status == "active" and (hinted in {tenant_id, tenant_name} or canonical_label == tenant_name):
                return {"id": tenant_id or normalize_tenant_id(tenant_name), "name": tenant_name, "status": "active"}
        return None

    def close(self) -> None:
        close = getattr(self.user_store, "close", None)
        if callable(close):
            close()

    def list_users(self, context: ExecutionContext) -> list[dict[str, Any]]:
        self._require_tenant_manager(context, context.tenant_id)
        roles_by_id = {role.role_id: role for role in self.policy_repository.list_roles()}
        assignments_by_user = self._assignments_by_user()
        users: list[dict[str, Any]] = []
        is_super_admin = self._is_super_admin(context.user_id)
        tenant_profile_lister = getattr(self.user_store, "list_profiles_for_tenant", None)
        profiles = (
            self.user_store.list_profiles()
            if is_super_admin or not callable(tenant_profile_lister)
            else tenant_profile_lister(context.tenant_id)
        )
        for profile in profiles:
            assignments = assignments_by_user.get(profile.user_id, [])
            visible_assignments = [
                assignment
                for assignment in assignments
                if roles_by_id.get(assignment.role_id)
                and (
                    is_super_admin
                    or assignment.tenant_id in (context.tenant_id, "*")
                    or roles_by_id[assignment.role_id].level == RoleLevel.SUPER_ADMIN
                )
            ]
            if not visible_assignments:
                continue
            users.append(self._serialize_user(profile, visible_assignments, roles_by_id))
        return sorted(users, key=lambda item: (0 if _has_super_admin_role(item) else 1, item["name"]))

    def list_roles(self, context: ExecutionContext) -> list[dict[str, Any]]:
        self._require_tenant_manager(context, context.tenant_id)
        return [
            self._serialize_role(role)
            for role in self.policy_repository.list_roles(context.tenant_id)
            if role.level == RoleLevel.SUPER_ADMIN or role.tenant_id in (context.tenant_id, None, "*")
        ]

    def login_by_email(self, email: str, tenant_hint: str | None = None, *, password: str | None = None) -> dict[str, Any]:
        contact = str(email or "").strip()
        if not contact:
            raise ValueError("email is required.")
        profile = self.find_profile_by_contact(contact)
        if profile is None or profile.status != "active":
            raise ValueError("用户不存在或已停用。")
        if password is not None and not self.verify_password(profile.user_id, password):
            raise ValueError("invalid_login_credentials")
        profile = UserProfile(
            user_id=profile.user_id,
            name=profile.name,
            department=profile.department,
            email=profile.email,
            status=profile.status,
            last_login="刚刚",
        )
        self._upsert_profile(profile)
        return self._session_payload_for_profile(profile, tenant_hint=tenant_hint)

    def session_for_user(self, user_id: str, tenant_hint: str | None = None) -> dict[str, Any]:
        profile = self.user_store.get_profile(user_id)
        if profile is None or profile.status != "active":
            raise PermissionError("user_account_inactive")
        return self._session_payload_for_profile(profile, tenant_hint=tenant_hint)

    def register_operator_by_email(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("user must be an object.")
        email = str(payload.get("email") or "").strip().lower()
        name = str(payload.get("name") or "").strip()
        institution = str(payload.get("institution") or payload.get("tenant") or "").strip()
        if not name or not email:
            raise ValueError("name and email are required.")
        if self.user_store.get_profile_by_email(email):
            raise ValueError("用户邮箱已存在，请直接登录或由管理员授权。")

        tenant_label = institution or self._active_tenant_names()[0]
        catalog_tenant = self._canonical_catalog_tenant(tenant_label)
        if catalog_tenant is None:
            raise ValueError("registration_institution_unknown")
        tenant_label = catalog_tenant["name"]
        tenant_id = catalog_tenant["id"]
        operator_role = self._find_role_by_name(tenant_id, "操作员")
        if operator_role is None:
            raise ValueError(f"机构默认操作员角色不存在，请检查：{tenant_label}")

        profile = UserProfile(
            user_id=_allocate_user_id(self.user_store, email),
            name=name,
            department=str(payload.get("department") or "").strip() or _tenant_label(tenant_id),
            email=email,
            status="active",
            last_login="刚刚",
        )
        saved = self._upsert_profile(profile)
        self.policy_repository.replace_user_assignments(
            saved.user_id,
            [RoleAssignment(saved.user_id, tenant_id, operator_role.role_id, granted_by=saved.user_id)],
        )
        return self._session_payload_for_profile(saved, tenant_hint=tenant_id)

    def submit_registration_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("user must be an object.")
        email = str(payload.get("email") or "").strip().lower()
        phone = _normalize_phone(payload.get("phone") or payload.get("mobile") or "")
        if not email and _looks_like_email(str(payload.get("contact") or payload.get("account") or "")):
            email = str(payload.get("contact") or payload.get("account") or "").strip().lower()
        if not phone:
            phone = _normalize_phone(payload.get("contact") or payload.get("account") or "")
        if email and not _looks_like_email(email):
            if not phone:
                phone = _normalize_phone(email)
            email = ""
        if not email and not phone:
            raise ValueError("registration_contact_required")
        institution = str(payload.get("institution") or payload.get("tenant") or "").strip()
        known = self._active_tenant_names()
        if not institution:
            raise ValueError("registration_institution_required")
        if institution not in known:
            raise ValueError("registration_institution_unknown")
        catalog_tenant = self._canonical_catalog_tenant(institution)
        if catalog_tenant is None:
            raise ValueError("registration_institution_unknown")
        institution = catalog_tenant["name"]
        tenant_id = catalog_tenant["id"]
        operator_role = self._find_role_by_name(tenant_id, "操作员")
        if operator_role is None:
            raise ValueError(f"机构默认操作员角色不存在，请检查：{institution}")
        contact_email = email or _phone_contact_email(phone)
        name = str(payload.get("name") or "").strip() or _default_registration_name(contact_email, phone)
        existing = self.find_profile_by_contact(email or phone)
        if existing is not None:
            if existing.status == "invited":
                raise ValueError("registration_already_pending")
            if existing.status == "active":
                raise ValueError("用户邮箱已存在，请直接登录或由管理员授权。")
        profile = UserProfile(
            user_id=existing.user_id if existing is not None else _allocate_user_id(self.user_store, contact_email),
            name=name,
            department=institution,
            email=contact_email,
            status="invited",
            last_login="未登录",
        )
        saved = self._upsert_profile(profile)
        self.set_account_password(saved.user_id, payload.get("password"))
        return {
            "status": "pending_approval",
            "request_id": saved.user_id,
            "institution": institution,
            "tenant_id": tenant_id,
            "contact": email or phone,
            "name": saved.name,
            "role": "操作员",
            "message": "注册申请已提交，请等待超级管理员在待办任务中同意。同意后将开通所选机构操作员权限；如需管理员权限，请联系超级管理员。",
        }

    def list_pending_registrations(self) -> list[dict[str, Any]]:
        pending: list[dict[str, Any]] = []
        for profile in self.user_store.list_profiles():
            if profile.status != "invited":
                continue
            pending.append(self._registration_record(profile))
        return sorted(pending, key=lambda item: item["name"])

    def review_registration(self, context: ExecutionContext, request_id: str, *, approved: bool) -> dict[str, Any]:
        if not self._is_super_admin(context.user_id):
            raise PermissionError("global_super_admin_required")
        user_id = str(request_id or "").strip().removeprefix("todo_reg_")
        if not user_id:
            raise ValueError("registration_not_found")
        profile = self.user_store.get_profile(user_id)
        if profile is None or profile.status != "invited":
            raise ValueError("registration_not_pending")
        institution = str(profile.department or "").strip()
        catalog_tenant = self._canonical_catalog_tenant(institution)
        if catalog_tenant is None:
            raise ValueError("registration_institution_unknown")
        tenant_id = catalog_tenant["id"]
        if approved:
            operator_role = self._find_role_by_name(tenant_id, "操作员")
            if operator_role is None:
                raise ValueError(f"机构默认操作员角色不存在，请检查：{institution}")
            activated = self._upsert_profile(
                UserProfile(
                    user_id=profile.user_id,
                    name=profile.name,
                    department=profile.department,
                    email=profile.email,
                    status="active",
                    last_login="未登录",
                )
            )
            self.policy_repository.replace_user_assignments(
                activated.user_id,
                [RoleAssignment(activated.user_id, tenant_id, operator_role.role_id, granted_by=context.user_id)],
            )
            return {
                "status": "approved",
                "request_id": activated.user_id,
                "user": self._session_payload_for_profile(activated, tenant_hint=tenant_id),
                "message": "已同意注册申请，账号已开通所选机构操作员权限。",
            }
        self._upsert_profile(
            UserProfile(
                user_id=profile.user_id,
                name=profile.name,
                department=profile.department,
                email=profile.email,
                status="inactive",
                last_login=profile.last_login,
            )
        )
        return {
            "status": "rejected",
            "request_id": profile.user_id,
            "message": "已拒绝注册申请，该账号不会开通。",
        }

    def find_profile_by_contact(self, contact: str) -> Any:
        text = str(contact or "").strip()
        if not text:
            return None
        if _looks_like_email(text):
            return self.user_store.get_profile_by_email(text.lower())
        phone = _normalize_phone(text)
        if not phone:
            return self.user_store.get_profile_by_email(text.lower())
        by_phone_email = self.user_store.get_profile_by_email(_phone_contact_email(phone))
        if by_phone_email is not None:
            return by_phone_email
        return self.user_store.get_profile_by_email(text.lower())

    def registration_todos(self) -> list[dict[str, Any]]:
        return [self._registration_todo(item) for item in self.list_pending_registrations()]

    def _registration_record(self, profile: UserProfile) -> dict[str, Any]:
        institution = str(profile.department or "").strip()
        contact = profile.email
        if contact.endswith("@users.sda.invalid"):
            contact = contact.split("@", 1)[0].removeprefix("phone.")
        return {
            "request_id": profile.user_id,
            "name": profile.name,
            "email": profile.email,
            "contact": contact,
            "institution": institution,
            "tenant_id": _tenant_id_from_label(institution),
            "role": "操作员",
            "status": "invited",
        }

    def _registration_todo(self, record: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        institution = str(record.get("institution") or "")
        name = str(record.get("name") or "")
        contact = str(record.get("contact") or record.get("email") or "")
        return {
            "id": f"todo_reg_{record['request_id']}",
            "title": f"注册申请：{name}（{institution}）",
            "description": (
                f"{name}申请加入{institution}，联系方式为{contact}。"
                "同意后开通该机构操作员权限；拒绝则申请失败。"
                "如需管理员或其他角色，请申请人联系超级管理员。"
            ),
            "status": "todo",
            "priority": "high",
            "dueDate": now[:10],
            "assignee": "超级管理员",
            "assigneeUserId": SUPER_ADMIN_USER_ID,
            "listName": "注册审批",
            "labels": ["注册审批"],
            "source": "system",
            "ownerUserId": SUPER_ADMIN_USER_ID,
            "createdBy": SUPER_ADMIN_USER_ID,
            "createdAt": now,
            "updatedAt": now,
            "relatedOrg": institution,
            "suggestion": "同意则开通操作员；拒绝则注册失败。",
            "registrationRequestId": record["request_id"],
        }

    def list_role_permissions(self, context: ExecutionContext) -> list[dict[str, Any]]:
        self._require_tenant_manager(context, context.tenant_id)
        permissions = []
        for tenant_label in _known_tenant_labels(self.policy_repository.list_roles()):
            tenant_id = normalize_tenant_id(tenant_label)
            if not self._can_view_tenant(context, tenant_id):
                continue
            permissions.append(self._serialize_institution_permission(tenant_label, tenant_id))
        return permissions

    def save_role_permission(self, context: ExecutionContext, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("permission must be an object.")
        tenant_label = str(payload.get("institution") or "").strip()
        tenant_id = _tenant_id_from_label(tenant_label)
        self._require_tenant_manager(context, tenant_id)

        admin_role = self._find_role_by_name(tenant_id, "管理员")
        operator_role = self._find_role_by_name(tenant_id, "操作员")
        if not admin_role or not operator_role:
            raise ValueError(f"机构默认角色不存在，请检查：{tenant_label}")

        role_configs = self._role_configs_from_payload(payload, tenant_id, admin_role, operator_role, context.user_id)
        roles_by_name = {
            role.name: role
            for role in self.policy_repository.list_roles(tenant_id)
            if role.tenant_id == tenant_id
        }

        for config in role_configs:
            role = roles_by_name.get(config["name"])
            if not role:
                continue
            is_admin_role = role.role_id == admin_role.role_id
            data_scopes = config["dataScopes"]
            self.policy_repository.replace_role_policies(
                role.role_id,
                _merge_preserved_role_policies(
                    self.policy_repository.get_role_policies(role.role_id),
                    _role_policies_from_ui(
                        role.role_id,
                        tenant_id,
                        menus=config["menus"],
                        data_scopes=data_scopes,
                        can_manage_tenant=False,
                        can_manage_system_config=False,
                        can_manage_roles=is_admin_role,
                        can_execute_analysis=bool(data_scopes),
                        can_create_metric=bool(data_scopes),
                        deny_role_manage=not is_admin_role,
                    ),
                ),
            )
            manageable_role_ids = {
                target.role_id
                for target in roles_by_name.values()
                if target.name in config["manageableRoles"]
                and target.tenant_id == tenant_id
                and target.role_id != role.role_id
                and target.level <= role.level
            }
            self.policy_repository.replace_manageable_role_ids(role.role_id, manageable_role_ids if is_admin_role else set())

        admin_config = next((config for config in role_configs if config["name"] == "管理员"), {})
        operator_config = next((config for config in role_configs if config["name"] == "操作员"), {})
        admin_menus = list(admin_config.get("menus") or [])
        admin_data = list(admin_config.get("dataScopes") or [])
        operator_menus = list(operator_config.get("menus") or [])
        operator_data = list(operator_config.get("dataScopes") or [])
        manageable_roles = list(admin_config.get("manageableRoles") or [])
        return {
            **payload,
            "id": str(payload.get("id") or tenant_id),
            "institution": _tenant_label(tenant_id),
            "adminMenus": admin_menus,
            "adminDataScopes": admin_data,
            "operatorSuperMenus": [],
            "operatorSuperDataScopes": [],
            "operatorAdminMenus": operator_menus,
            "operatorAdminDataScopes": operator_data,
            "manageableRoles": manageable_roles,
            "customRoles": self._custom_role_names(tenant_id),
            "roleConfigs": self._serialize_role_configs(tenant_id),
            "updatedBy": context.user_id,
            "updatedAt": "刚刚",
        }

    def upsert_user(self, context: ExecutionContext, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("user must be an object.")
        requested_user_id = str(payload.get("id") or payload.get("user_id") or "").strip()
        requested_email = str(payload.get("email") or "").strip()
        existing_by_email = self.user_store.get_profile_by_email(requested_email) if requested_email else None
        if existing_by_email and not requested_user_id:
            raise ValueError("用户邮箱已存在，请检查……")
        profile = self._profile_from_payload(payload)
        if existing_by_email and existing_by_email.user_id != profile.user_id:
            raise ValueError("用户邮箱已存在，请检查……")

        incoming = self._assignments_from_payload(context, profile.user_id, payload)
        for assignment in incoming:
            role = self.policy_repository.get_role(assignment.role_id)
            if not role:
                raise ValueError(f"unknown role: {assignment.role_id}")
            self._require_can_grant_role(context, assignment.tenant_id, role)
        assignments = _merge_user_assignments(
            self.policy_repository.list_user_assignments(profile.user_id),
            incoming,
        )

        # Relational identity lookup requires an active row while grants are written.
        grant_profile = profile if profile.status == "active" else UserProfile(
            user_id=profile.user_id,
            name=profile.name,
            department=profile.department,
            email=profile.email,
            status="active",
            last_login=profile.last_login,
        )
        saved = self._upsert_profile(grant_profile)
        self.policy_repository.replace_user_assignments(saved.user_id, assignments)
        # Bind department after memberships exist, then persist the requested status.
        saved = self._upsert_profile(profile)
        roles_by_id = {role.role_id: role for role in self.policy_repository.list_roles()}
        return self._serialize_user(saved, assignments, roles_by_id)

    def delete_user(self, context: ExecutionContext, user_id: str) -> bool:
        user_id = user_id.strip()
        if not user_id:
            raise ValueError("user_id is required.")
        if user_id == context.user_id:
            raise PermissionError("current user cannot delete itself.")

        assignments = self.policy_repository.list_user_assignments(user_id)
        for assignment in assignments:
            role = self.policy_repository.get_role(assignment.role_id)
            if not role:
                continue
            if role.level == RoleLevel.SUPER_ADMIN:
                raise PermissionError("super administrator cannot be deleted from tenant settings.")
            self._require_can_grant_role(context, assignment.tenant_id, role)

        self.policy_repository.delete_user_assignments(user_id)
        return self.user_store.delete_profile(user_id)

    def _assignments_by_user(self) -> dict[str, list[RoleAssignment]]:
        grouped: dict[str, list[RoleAssignment]] = defaultdict(list)
        for assignment in self.policy_repository.list_user_assignments():
            grouped[assignment.user_id].append(assignment)
        return grouped

    def verify_password(self, user_id: str, password: str) -> bool:
        from .passwords import DEFAULT_ACCOUNT_PASSWORD, hash_password, verify_password

        stored = self.user_store.get_password_hash(user_id)
        if stored:
            return verify_password(stored, password)
        if str(password or "") != DEFAULT_ACCOUNT_PASSWORD:
            return False
        self.user_store.set_password_hash(user_id, hash_password(DEFAULT_ACCOUNT_PASSWORD))
        return True

    def set_account_password(self, user_id: str, password: Any = None) -> None:
        from .passwords import DEFAULT_ACCOUNT_PASSWORD, MIN_PASSWORD_LENGTH, hash_password

        text = str(password or "").strip() or DEFAULT_ACCOUNT_PASSWORD
        if len(text) < MIN_PASSWORD_LENGTH:
            raise ValueError("password_new_too_short")
        self.user_store.set_password_hash(user_id, hash_password(text))

    def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        from .passwords import MIN_PASSWORD_LENGTH, hash_password

        current = str(current_password or "")
        incoming = str(new_password or "").strip()
        if not current:
            raise ValueError("password_current_required")
        if not incoming:
            raise ValueError("password_new_required")
        if len(incoming) < MIN_PASSWORD_LENGTH:
            raise ValueError("password_new_too_short")
        if incoming == current:
            raise ValueError("password_new_same_as_current")
        if not self.verify_password(user_id, current):
            raise ValueError("password_current_incorrect")
        self.user_store.set_password_hash(user_id, hash_password(incoming))

    def _upsert_profile(self, profile: UserProfile) -> UserProfile:
        try:
            return self.user_store.upsert_profile(profile)
        except Exception as exc:
            _raise_profile_constraint_error(exc)

    def _profile_from_payload(self, payload: dict[str, Any]) -> UserProfile:
        email = str(payload.get("email") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not name or not email:
            raise ValueError("name and email are required.")
        user_id = str(payload.get("id") or payload.get("user_id") or "").strip()
        if not user_id:
            existing = self.user_store.get_profile_by_email(email)
            user_id = existing.user_id if existing else _allocate_user_id(self.user_store, email)
        return UserProfile(
            user_id=user_id,
            name=name,
            department=str(payload.get("department") or "").strip() or "未分配部门",
            email=email,
            status=_normalize_status(payload.get("status")),
            last_login=str(payload.get("lastLogin") or payload.get("last_login") or "未登录").strip() or "未登录",
        )

    def _assignments_from_payload(
        self,
        context: ExecutionContext,
        user_id: str,
        payload: dict[str, Any],
    ) -> list[RoleAssignment]:
        tenant_roles = payload.get("tenantRoles") or payload.get("tenant_roles") or []
        if not isinstance(tenant_roles, list) or not tenant_roles:
            tenant_roles = [{"tenant": _tenant_label(context.tenant_id), "role": "操作员"}]

        assignments: list[RoleAssignment] = []
        for item in tenant_roles:
            if not isinstance(item, dict):
                raise ValueError("tenantRoles must contain objects.")
            role_name = str(item.get("role") or "").strip()
            tenant_value = str(item.get("tenant") or "").strip()
            if role_name == "超级管理员":
                assignments.append(RoleAssignment(user_id, "*", SUPER_ADMIN_ROLE_ID, granted_by=context.user_id))
                continue
            tenant_code = str(item.get("tenantId") or item.get("tenant_id") or "").strip()
            tenant_id = self._resolve_assignment_tenant_id(tenant_code, tenant_value, context)
            role = self._find_role_by_name(tenant_id, role_name)
            if role is None:
                raise ValueError(f"角色不存在，请检查：{tenant_value} · {role_name}")
            assignments.append(RoleAssignment(user_id, tenant_id, role.role_id, granted_by=context.user_id))
        return _dedupe_assignments(assignments)

    def _find_role_by_name(self, tenant_id: str, role_name: str) -> Role | None:
        for role in self.policy_repository.list_roles(tenant_id):
            if role.tenant_id == tenant_id and role.name == role_name:
                return role
        return None

    def _resolve_assignment_tenant_id(self, tenant_code: str, tenant_value: str, context: ExecutionContext) -> str:
        raw = str(tenant_code or tenant_value or _tenant_label(context.tenant_id)).strip()
        if raw in {"*", "全部机构"}:
            return "*"
        candidate = _tenant_id_from_label(raw)
        if any(role.tenant_id == candidate for role in self.policy_repository.list_roles(candidate)):
            return candidate
        wanted = {item for item in (_tenant_label(candidate), tenant_value.strip(), raw) if item}
        for role in self.policy_repository.list_roles():
            tenant_id = str(role.tenant_id or "")
            if not tenant_id or tenant_id == "*":
                continue
            if tenant_id in wanted or _tenant_label(tenant_id) in wanted:
                return tenant_id
        return candidate

    def _require_tenant_manager(self, context: ExecutionContext, tenant_id: str) -> None:
        if self._is_super_admin(context.user_id):
            return
        scoped_context = ExecutionContext(user_id=context.user_id, tenant_id=tenant_id, page_context=context.page_context)
        self.permission_broker.require_resource(scoped_context, "role:*", "manage")

    def _require_can_grant_role(self, context: ExecutionContext, tenant_id: str, role: Role) -> None:
        if role.level == RoleLevel.SUPER_ADMIN:
            if not self._is_super_admin(context.user_id):
                raise PermissionError("only super administrator can grant global super administrator.")
            return
        if self._is_super_admin(context.user_id):
            return
        if not self.permission_broker.enforcer.can_manage_role(context.user_id, tenant_id, role.role_id):
            raise PermissionError(f"Permission denied: cannot grant role {role.name}")

    def _is_super_admin(self, user_id: str) -> bool:
        for assignment in self.policy_repository.list_user_assignments(user_id):
            role = self.policy_repository.get_role(assignment.role_id)
            if role and role.level == RoleLevel.SUPER_ADMIN:
                return True
        return False

    def _can_view_tenant(self, context: ExecutionContext, tenant_id: str) -> bool:
        if self._is_super_admin(context.user_id):
            return True
        return context.tenant_id == tenant_id

    def _custom_role_names(self, tenant_id: str) -> list[str]:
        return [
            role.name
            for role in self.policy_repository.list_roles(tenant_id)
            if role.tenant_id == tenant_id and not role.is_system
        ]

    def _delete_custom_role(self, tenant_id: str, name: str) -> None:
        role = self._find_role_by_name(tenant_id, name)
        if not role or role.is_system:
            return
        operator = self._find_role_by_name(tenant_id, "操作员")
        affected = [item.user_id for item in self.policy_repository.list_user_assignments() if item.role_id == role.role_id]
        for user_id in dict.fromkeys(affected):
            existing = self.policy_repository.list_user_assignments(user_id)
            kept = [item for item in existing if item.role_id != role.role_id]
            if operator and not any(item.role_id == operator.role_id and item.tenant_id == tenant_id for item in kept):
                kept.append(RoleAssignment(user_id, tenant_id, operator.role_id, granted_by=SUPER_ADMIN_USER_ID))
            self.policy_repository.replace_user_assignments(user_id, kept)
        delete_role = getattr(self.policy_repository, "delete_role", None)
        if callable(delete_role):
            delete_role(role.role_id)

    def _role_configs_from_payload(
        self,
        payload: dict[str, Any],
        tenant_id: str,
        admin_role: Role,
        operator_role: Role,
        created_by: str,
    ) -> list[dict[str, Any]]:
        raw_configs = payload.get("roleConfigs")
        if isinstance(raw_configs, list) and raw_configs:
            configs = [_normalize_role_config(item, tenant_id) for item in raw_configs if isinstance(item, dict)]
        else:
            configs = [
                {
                    "roleId": admin_role.role_id,
                    "name": "管理员",
                    "roleType": "admin",
                    "isSystem": True,
                    "menus": _normalize_string_list(payload.get("adminMenus"), PERMISSION_MENU_LABELS),
                    "dataScopes": _normalize_string_list(payload.get("adminDataScopes"), PERMISSION_DATA_SCOPES),
                    "manageableRoles": _normalize_string_list(
                        payload.get("manageableRoles"),
                        ["操作员", *self._custom_role_names(tenant_id)],
                    ),
                },
                {
                    "roleId": operator_role.role_id,
                    "name": "操作员",
                    "roleType": "operator",
                    "isSystem": True,
                    "menus": _normalize_string_list(
                        payload.get("operatorSuperMenus") or payload.get("operatorAdminMenus"),
                        PERMISSION_MENU_LABELS,
                    ),
                    "dataScopes": _normalize_string_list(
                        payload.get("operatorSuperDataScopes") or payload.get("operatorAdminDataScopes"),
                        PERMISSION_DATA_SCOPES,
                    ),
                    "manageableRoles": [],
                },
            ]

        existing_names = {
            role.name
            for role in self.policy_repository.list_roles(tenant_id)
            if role.tenant_id == tenant_id
        }
        for config in configs:
            if config["name"] in _SYSTEM_ROLE_NAMES or config["name"] in existing_names:
                continue
            role = Role(
                role_id=tenant_role_id(tenant_id, config["name"]),
                tenant_id=tenant_id,
                name=config["name"],
                level=RoleLevel.OPERATOR,
                is_system=False,
                created_by=created_by,
            )
            self.policy_repository.upsert_role(role)
            existing_names.add(config["name"])

        configured_names = {config["name"] for config in configs}
        existing_custom = self._custom_role_names(tenant_id)
        if isinstance(payload.get("roleConfigs"), list) and payload.get("roleConfigs"):
            for name in existing_custom:
                if name not in configured_names:
                    self._delete_custom_role(tenant_id, name)
        else:
            for name in existing_custom:
                if name not in configured_names:
                    configs.append(
                        {
                            "roleId": tenant_role_id(tenant_id, name),
                            "name": name,
                            "roleType": "custom",
                            "isSystem": False,
                            "menus": [],
                            "dataScopes": [],
                            "manageableRoles": [],
                        }
                    )
        return configs

    def _serialize_role_configs(self, tenant_id: str) -> list[dict[str, Any]]:
        roles = [
            role
            for role in self.policy_repository.list_roles(tenant_id)
            if role.tenant_id == tenant_id
        ]
        role_order = {"管理员": 0, "操作员": 1}
        return [
            {
                "roleId": role.role_id,
                "name": role.name,
                "roleType": "admin" if role.name == "管理员" else "operator" if role.name == "操作员" else "custom",
                "isSystem": role.is_system,
                "menus": _labels_from_menu_policies(self.policy_repository.get_role_policies(role.role_id)),
                "dataScopes": _data_scopes_from_policies(self.policy_repository.get_role_policies(role.role_id)),
                "manageableRoles": _role_names_from_ids(
                    self.policy_repository,
                    self.policy_repository.get_manageable_role_ids(role.role_id),
                ),
            }
            for role in sorted(roles, key=lambda item: (role_order.get(item.name, 10), item.name))
        ]

    def _serialize_institution_permission(self, tenant_label: str, tenant_id: str) -> dict[str, Any]:
        admin_role = self._find_role_by_name(tenant_id, "管理员")
        operator_role = self._find_role_by_name(tenant_id, "操作员")
        custom_roles = self._custom_role_names(tenant_id)
        if not admin_role or not operator_role:
            return {
                "id": tenant_id,
                "institution": tenant_label,
                "adminMenus": PERMISSION_MENU_LABELS,
                "adminDataScopes": PERMISSION_DATA_SCOPES,
                "operatorSuperMenus": [],
                "operatorSuperDataScopes": [],
                "operatorAdminMenus": [],
                "operatorAdminDataScopes": [],
                "manageableRoles": [],
                "customRoles": custom_roles,
                "roleConfigs": [],
                "updatedBy": "system",
                "updatedAt": "初始化",
            }
        return {
            "id": tenant_id,
            "institution": tenant_label,
            "adminMenus": _labels_from_menu_policies(self.policy_repository.get_role_policies(admin_role.role_id)),
            "adminDataScopes": _data_scopes_from_policies(self.policy_repository.get_role_policies(admin_role.role_id)),
            "operatorSuperMenus": [],
            "operatorSuperDataScopes": [],
            "operatorAdminMenus": _labels_from_menu_policies(self.policy_repository.get_role_policies(operator_role.role_id)),
            "operatorAdminDataScopes": _data_scopes_from_policies(self.policy_repository.get_role_policies(operator_role.role_id)),
            "manageableRoles": _role_names_from_ids(
                self.policy_repository,
                self.policy_repository.get_manageable_role_ids(admin_role.role_id),
            ),
            "customRoles": custom_roles,
            "roleConfigs": self._serialize_role_configs(tenant_id),
            "updatedBy": "后端策略库",
            "updatedAt": "实时",
        }

    @staticmethod
    def _serialize_role(role: Role) -> dict[str, Any]:
        return {
            "role_id": role.role_id,
            "tenant_id": role.tenant_id,
            "tenant": "全部机构" if role.level == RoleLevel.SUPER_ADMIN else _tenant_label(role.tenant_id or ""),
            "name": role.name,
            "level": int(role.level),
            "is_system": role.is_system,
            "created_by": role.created_by,
        }

    @staticmethod
    def _serialize_user(
        profile: UserProfile,
        assignments: list[RoleAssignment],
        roles_by_id: dict[str, Role],
    ) -> dict[str, Any]:
        tenant_roles = []
        for assignment in assignments:
            role = roles_by_id.get(assignment.role_id)
            if not role:
                continue
            tenant_roles.append(
                {
                    "tenant": "全部机构" if role.level == RoleLevel.SUPER_ADMIN else _tenant_label(assignment.tenant_id),
                    "tenantId": "*" if role.level == RoleLevel.SUPER_ADMIN else assignment.tenant_id,
                    "role": "超级管理员" if role.level == RoleLevel.SUPER_ADMIN else role.name,
                }
            )
        return {
            "id": profile.user_id,
            "name": profile.name,
            "department": profile.department,
            "email": profile.email,
            "status": profile.status,
            "lastLogin": profile.last_login,
            "tenantRoles": tenant_roles,
        }

    def _session_payload_for_profile(self, profile: UserProfile, tenant_hint: str | None = None) -> dict[str, Any]:
        roles_by_id = {role.role_id: role for role in self.policy_repository.list_roles()}
        assignments = self.policy_repository.list_user_assignments(profile.user_id)
        user = self._serialize_user(profile, assignments, roles_by_id)
        selectable_tenants = self._selectable_catalog_tenants(profile.user_id, assignments, roles_by_id)
        if not selectable_tenants:
            raise PermissionError("当前用户没有可访问机构。")
        selected_tenant = self._select_catalog_session_tenant(selectable_tenants, tenant_hint)
        return {
            "user": user,
            "tenant_id": selected_tenant["id"],
            "institution": selected_tenant["name"],
            "institutions": [item["name"] for item in selectable_tenants],
            "is_super_admin": any(role.get("role") == "超级管理员" for role in user["tenantRoles"]),
        }

    def _selectable_catalog_tenants(
        self,
        user_id: str,
        assignments: list[RoleAssignment],
        roles_by_id: dict[str, Role],
    ) -> list[dict[str, str]]:
        active = self._active_tenant_catalog()
        if self._is_super_admin(user_id):
            return active
        authorized_ids = {
            assignment.tenant_id
            for assignment in assignments
            if (role := roles_by_id.get(assignment.role_id)) is not None and role.level != RoleLevel.SUPER_ADMIN
        }
        return [item for item in active if item["id"] in authorized_ids]

    @staticmethod
    def _select_session_tenant(selectable_tenants: list[str], tenant_hint: str | None) -> str:
        hinted = str(tenant_hint or "").strip()
        if hinted:
            hinted_label = _canonical_tenant_label(hinted)
            if hinted_label in selectable_tenants:
                return _tenant_id_from_label(hinted_label)
            raise PermissionError("session_tenant_not_authorized")
        return _tenant_id_from_label(selectable_tenants[0])

    def _select_catalog_session_tenant(
        self,
        selectable_tenants: list[dict[str, str]],
        tenant_hint: str | None,
    ) -> dict[str, str]:
        if tenant_hint:
            selected = self._canonical_catalog_tenant(tenant_hint)
            selectable_ids = {item["id"] for item in selectable_tenants}
            if selected is None or selected["id"] not in selectable_ids:
                raise PermissionError("session_tenant_not_authorized")
            return selected
        return selectable_tenants[0]


def _tenant_id_from_label(value: str) -> str:
    value = value.strip()
    if value.startswith("tenant:"):
        return value
    return normalize_tenant_id(value)


def _tenant_label(tenant_id: str) -> str:
    return tenant_id.removeprefix("tenant:")


_TENANT_SLUGS = {
    "华兴银行": "huaxing",
    "广州银行": "guangzhou",
    "兰州银行": "lanzhou",
    "汉口银行": "hankou",
    "石嘴山银行": "shizuishan",
    "郑州银行": "zhengzhou",
    "临商银行": "linshang",
    "瑞丰银行": "ruifeng",
    "南京银行": "nanjing",
    "兴业消金": "xingye-consumer-finance",
    "三峡银行": "sanxia",
}
_TENANT_LABELS_BY_SLUG = {slug: label for label, slug in _TENANT_SLUGS.items() if label in OPERATING_TENANTS}


def _canonical_tenant_label(value: str) -> str:
    label = _tenant_label(str(value or "").strip())
    return _TENANT_LABELS_BY_SLUG.get(label, label)


def _known_tenant_labels(roles: list[Role]) -> list[str]:
    labels = {
        _tenant_label(role.tenant_id)
        for role in roles
        if role.tenant_id and role.tenant_id.startswith("tenant:")
        and _tenant_label(role.tenant_id) not in {"sda-internal", "SDA 内部环境"}
    }
    return sorted(labels)


def _normalize_string_list(value: Any, allowed: list[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed_set = set(allowed)
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text in allowed_set and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_role_config(value: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    raw_name = str(value.get("name") or "").strip()
    if raw_name in {"机构管理员", "管理员"}:
        name = "管理员"
        role_type = "admin"
        is_system = True
    elif raw_name in {"机构操作员", "操作员"}:
        name = "操作员"
        role_type = "operator"
        is_system = True
    else:
        name = raw_name[:40]
        role_type = "custom"
        is_system = False
    if not name:
        raise ValueError("role name is required.")
    return {
        "roleId": str(value.get("roleId") or tenant_role_id(tenant_id, name)).strip(),
        "name": name,
        "roleType": str(value.get("roleType") or role_type).strip() or role_type,
        "isSystem": bool(value.get("isSystem") if "isSystem" in value else is_system),
        "menus": _normalize_string_list(value.get("menus"), PERMISSION_MENU_LABELS),
        "dataScopes": _normalize_string_list(value.get("dataScopes"), PERMISSION_DATA_SCOPES),
        "manageableRoles": _normalize_free_string_list(value.get("manageableRoles")),
    }


def _normalize_free_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()[:40]
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _role_policies_from_ui(
    role_id: str,
    tenant_id: str,
    menus: list[str],
    data_scopes: list[str],
    can_manage_tenant: bool,
    can_manage_system_config: bool,
    can_manage_roles: bool,
    can_execute_analysis: bool,
    can_create_metric: bool,
    deny_role_manage: bool = False,
) -> list[PermissionPolicy]:
    policies: list[PermissionPolicy] = []
    for key in sorted(_menu_keys_from_labels(menus)):
        policies.append(PermissionPolicy(role_id, tenant_id, f"menu:{key}", "read", priority=20))
    if data_scopes:
        policies.append(PermissionPolicy(role_id, tenant_id, "metric:*", "read", attrs={"tenant_id": tenant_id}, priority=30))
    if can_create_metric:
        policies.append(PermissionPolicy(role_id, tenant_id, "metric:*", "create", attrs={"tenant_id": tenant_id}, priority=35))
    if can_manage_tenant:
        policies.append(PermissionPolicy(role_id, tenant_id, "tenant:*", "manage", attrs={"tenant_id": tenant_id}, priority=30))
    if can_manage_roles:
        policies.append(PermissionPolicy(role_id, tenant_id, "role:*", "manage", attrs={"tenant_id": tenant_id}, priority=30))
    if can_manage_system_config:
        policies.extend(
            [
                PermissionPolicy(role_id, tenant_id, "system_config:*", "read", attrs={"tenant_id": tenant_id}, priority=30),
                PermissionPolicy(role_id, tenant_id, "system_config:*", "manage", attrs={"tenant_id": tenant_id}, priority=35),
            ]
        )
    if can_execute_analysis:
        policies.extend(
            [
                PermissionPolicy(role_id, tenant_id, "skill:supersonic.query", "execute", priority=30),
                PermissionPolicy(role_id, tenant_id, "mcp:database.query", "execute", priority=35),
                PermissionPolicy(role_id, tenant_id, "mcp:database.schema", "execute", priority=35),
                PermissionPolicy(role_id, tenant_id, "mcp:knowledge.search", "execute", priority=35),
            ]
        )
    if "知识记忆" in menus:
        policies.append(PermissionPolicy(role_id, tenant_id, "mcp:knowledge.ingest", "execute", priority=40))
    if "我的报告" in menus or "经营周报" in menus:
        policies.extend(
            [
                PermissionPolicy(role_id, tenant_id, "report:*", "read", attrs={"tenant_id": tenant_id}, priority=30),
                PermissionPolicy(role_id, tenant_id, "report:*", "create", attrs={"tenant_id": tenant_id}, priority=35),
            ]
        )
    if deny_role_manage:
        policies.append(PermissionPolicy(role_id, tenant_id, "role:*", "manage", effect="deny", priority=10))
    return policies


def _menu_keys_from_labels(labels: list[str]) -> set[str]:
    keys = set(_MANDATORY_MENU_KEYS)
    for label in labels:
        keys.update(_MENU_LABEL_TO_KEYS.get(label, set()))
    keys.discard("dashboard")
    return keys


def _labels_from_menu_policies(policies: list[PermissionPolicy]) -> list[str]:
    objects = {policy.obj.removeprefix("menu:") for policy in policies if policy.obj.startswith("menu:")}
    if "menu:*" in {policy.obj for policy in policies}:
        return list(PERMISSION_MENU_LABELS)
    labels = [
        label
        for label in PERMISSION_MENU_LABELS
        if _MENU_LABEL_TO_KEYS.get(label, set()) & objects
    ]
    return labels


def _data_scopes_from_policies(policies: list[PermissionPolicy]) -> list[str]:
    if any(policy.obj == "metric:*" and policy.act in {"read", "*"} and policy.effect == "allow" for policy in policies):
        return list(PERMISSION_DATA_SCOPES)
    return []


def _role_names_from_ids(policy_repository: PolicyRepository, role_ids: set[str]) -> list[str]:
    names: list[str] = []
    for role_id in sorted(role_ids):
        role = policy_repository.get_role(role_id)
        if role and role.name not in names:
            names.append(role.name)
    return names


_UI_MANAGED_POLICY_PREFIXES = (
    "menu:",
    "metric:",
    "role:",
    "skill:supersonic.query",
    "mcp:database.",
    "mcp:knowledge.",
    "report:",
)


def _is_ui_managed_policy(policy: PermissionPolicy) -> bool:
    return any(policy.obj == prefix or policy.obj.startswith(prefix) for prefix in _UI_MANAGED_POLICY_PREFIXES)


def _merge_preserved_role_policies(
    existing: list[PermissionPolicy],
    rewritten: list[PermissionPolicy],
) -> list[PermissionPolicy]:
    preserved = [policy for policy in existing if not _is_ui_managed_policy(policy)]
    seen = {(policy.obj, policy.act, policy.effect) for policy in rewritten}
    merged = list(rewritten)
    for policy in preserved:
        key = (policy.obj, policy.act, policy.effect)
        if key in seen:
            continue
        seen.add(key)
        merged.append(policy)
    return merged


def _merge_user_assignments(
    existing: list[RoleAssignment],
    incoming: list[RoleAssignment],
) -> list[RoleAssignment]:
    incoming_tenants = {assignment.tenant_id for assignment in incoming}
    preserved = [assignment for assignment in existing if assignment.tenant_id not in incoming_tenants]
    return _dedupe_assignments([*preserved, *incoming])


def _looks_like_email(value: str) -> bool:
    text = str(value or "").strip()
    if "@" not in text or text.startswith("@") or text.endswith("@"):
        return False
    local, _, domain = text.partition("@")
    return bool(local) and "." in domain


def _normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if 7 <= len(digits) <= 15:
        return digits
    return ""


def _phone_contact_email(phone: str) -> str:
    return f"phone.{phone}@users.sda.invalid"


def _default_registration_name(email: str, phone: str) -> str:
    if phone:
        return f"用户{phone[-4:]}"
    local = email.split("@", 1)[0].strip()
    return local or "新用户"


def _user_id_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0].lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", local_part).strip("_")
    return f"u_{slug or 'user'}"


def _allocate_user_id(user_store: UserDirectoryStore, email: str) -> str:
    base = _user_id_from_email(email)
    existing = user_store.get_profile(base)
    if existing is None or existing.email.lower() == email.strip().lower():
        return base
    suffix = 2
    while True:
        candidate = f"{base}_{suffix}"
        if user_store.get_profile(candidate) is None:
            return candidate
        suffix += 1


def _is_unique_violation(exc: BaseException) -> bool:
    if getattr(exc, "pgcode", None) == "23505" or getattr(exc, "errno", None) == 1062:
        return True
    text = str(exc).lower()
    return "unique" in text or "duplicate" in text


def _raise_profile_constraint_error(exc: BaseException) -> None:
    if _is_unique_violation(exc):
        text = str(exc).lower()
        if "external_subject" in text:
            raise ValueError("用户标识已存在，请检查……") from exc
        raise ValueError("用户邮箱已存在，请检查……") from exc
    raise exc


def _normalize_status(value: Any) -> str:
    status = str(value or "active").strip()
    return status if status in {"active", "inactive"} else "active"


def _dedupe_assignments(assignments: list[RoleAssignment]) -> list[RoleAssignment]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[RoleAssignment] = []
    for assignment in assignments:
        key = (assignment.user_id, assignment.tenant_id, assignment.role_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(assignment)
    return deduped


def _has_super_admin_role(user: dict[str, Any]) -> bool:
    return any(role.get("role") == "超级管理员" for role in user.get("tenantRoles", []))

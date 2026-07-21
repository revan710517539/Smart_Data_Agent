# 多租户权限管理模块设计

## 1. 设计目标

本模块用于 Smart Data Agent 的企业级多租户权限治理。设计参考 Casbin 的 PERM 思想，但不直接依赖 Casbin：

- `Request`: 用户在某机构下访问某资源并执行某动作。
- `Policy`: 角色在某机构下对资源和动作的授权策略。
- `Role`: 用户和角色在机构域内绑定。
- `Matcher`: 判断请求、角色、策略、资源属性是否匹配。
- `Effect`: 默认拒绝，允许策略命中则通过，拒绝策略优先。

结合平台架构，权限检查应放在这些链路前置：

- Application Layer 页面路由、按钮展示。
- Intent & Context Router 构造上下文前。
- Skill Registry / MCP Gateway 调用前。
- SuperSonic 语义查询和 SQL 执行前。
- Python Sandbox、数据导出、指标新增/修改/删除前。

## 2. 多租户与角色规则

机构是权限域 `dom`。同一用户可以在多个机构有不同角色：

```text
g, user_001, tenant_admin, tenant_huaxing
g, user_001, operator, tenant_guangzhou
```

每个机构默认两个角色：

- 管理员：本机构全权限，可创建小于或等于自身权限的新角色。
- 操作员：默认继承管理员除角色管理外的权限。

超级管理员为全局单例角色：

- 可添加机构、数据源、用户。
- 可给同一用户授予跨多个机构的角色。
- 可编辑每个用户、角色下的权限。
- 不挂在任何单个机构下，不能在每个机构内重复创建。
- 和机构管理员授权冲突时，以全局覆盖授权为准。

代码约束位于：

```text
backend/authz/rbac.py
```

其中 `SUPER_ADMIN_ROLE_ID` 表示唯一全局超管角色，`build_default_rbac_seed()` 只会创建一个全局超级管理员角色，机构下只创建管理员、操作员和自定义角色。

## 3. 在营机构初始化

从 `7月3日金科重点项目双周会.docx` 中提取到的在运营机构已固化到：

```text
backend/authz/seed.py
src/app/data/operatingTenants.ts
```

机构清单：

- 华兴银行
- 广州银行
- 兰州银行
- 汉口银行
- 石嘴山银行
- 郑州银行
- 临商银行
- 瑞丰银行
- 南京银行
- 兴业消金
- 三峡银行

超级管理员进入系统后，用户管理、角色权限、数据接入、机构授权都应默认基于这份机构清单展示。角色权限页面中，超级管理员只在全局管理全集中展示；机构权限卡片只展示机构管理员、机构操作员和自定义角色。

## 4. 数据库表结构

DDL 位于：

```text
backend/authz/schema.sql
```

核心表：

- `auth_tenants`: 机构表。
- `auth_users`: 用户表。
- `auth_roles`: 角色表，支持全局超级管理员和机构内角色。
- `auth_resources`: 权限资源表，统一承载菜单、按钮、机构、指标、角色、Skill、模型、数据源。
- `auth_permissions`: 策略表，保存资源、动作、效果和 ABAC 条件。
- `auth_user_roles`: 用户-角色-机构关联，支持同一用户跨机构不同角色。
- `auth_role_permissions`: 角色-权限关联。
- `auth_role_manageable_roles`: 当前角色可管理哪些角色。
- `auth_metrics`: 指标资源表，包含 `created_by`，支持机构内指标新增人追踪。
- `auth_audit_logs`: 权限和数据访问审计。

## 5. 权限模型

请求对象：

```python
AuthRequest(
    sub="user_001",
    dom="tenant_huaxing",
    obj="metric:loan_balance",
    act="read",
    attrs={
        "resource_type": "metric",
        "tenant_id": "tenant_huaxing",
        "metric_ids": {"m_balance"},
        "fields": {"branch_id", "metric_value"},
    },
)
```

策略对象：

```python
PermissionPolicy(
    role_id="operator",
    tenant_id="tenant_huaxing",
    obj="metric:*",
    act="read",
    effect="allow",
    attrs={
        "tenant_id": "tenant_huaxing",
        "resource_type": "metric",
        "metric_ids": ["m_balance", "m_loan"],
        "fields": ["branch_id", "metric_value"],
        "row_filter": {"tenant_id": "tenant_huaxing"},
    },
)
```

Matcher 伪代码：

```text
roles = load_roles(request.sub, request.dom)
for role in roles:
    policies = load_policies(role)
    for policy in policies ordered by priority:
        if domain_match(request.dom, policy.dom)
           and object_match(request.obj, policy.obj)
           and action_match(request.act, policy.act)
           and attribute_match(request.attrs, policy.attrs):
              if policy.effect == deny:
                  return false
              allow = true
return allow
```

## 6. 菜单权限规则

菜单以树形资源入库：

```text
menu:business-analysis
menu:business-analysis.weekly-report
menu:business-analysis.funnel
```

规则：

- 选择一级菜单时，自动包含所有二级菜单。
- 只选择二级菜单时，页面展示二级菜单和对应一级菜单，不展示其他菜单。
- `系统管理 / 审计日志` 和 `系统管理 / 系统配置` 为默认展示资源，所有角色默认可见，并自动带出父级 `系统管理`。

对应实现：

```python
from backend.authz import expand_menu_selection

visible_menus = expand_menu_selection(["business-analysis.weekly-report"])
```

## 7. 指标权限规则

指标属于机构域：

```text
tenant_id + metric_key 唯一
```

默认规则：

- 机构角色默认可看本机构全量指标。
- 如果角色不允许看某指标，则在角色权限中移除该指标。
- 本机构管理员和操作员拥有指标 `read/create`。
- 超级管理员拥有指标 `read/create/update/delete`。
- 机构新增指标必须写入 `created_by`。

行级/字段级权限通过策略 `attrs` 表达：

```json
{
  "row_filter": {"tenant_id": "tenant_huaxing", "branch_id": ["001", "002"]},
  "fields": ["branch_id", "metric_value", "stat_date"]
}
```

## 8. 可管理角色规则

角色层级：

```text
超级管理员 100 > 机构管理员 50 > 机构操作员 10
```

可管理角色必须满足：

- 超级管理员可管理所有机构的所有角色。
- 机构管理员只能管理本机构角色。
- 可管理目标角色权限必须小于或等于当前角色。
- 机构管理员新建自定义角色时，权限不得超过自己的权限集合。

## 9. 当前代码入口

```text
backend/authz/models.py       # Request/Policy/Role 数据模型
backend/authz/repository.py   # 策略仓库边界和内存实现
backend/authz/enforcer.py     # AuthEnforcer 鉴权核心
backend/authz/rbac.py         # 全局单例超管、机构默认角色、RBAC种子和校验
backend/authz/seed.py         # 在营机构、默认角色、菜单资源和菜单展开规则
backend/authz/schema.sql      # PostgreSQL 表结构
backend/authz/tests/          # 单元测试
backend/platform/access/      # 用户目录、用户-角色授权服务和系统管理 API 支撑
```

系统管理页面当前已接入的后端访问控制 API：

```text
GET    /api/access/users      # 当前机构下可管理用户、角色列表
POST   /api/access/user       # 保存用户资料并替换用户-角色授权
DELETE /api/access/user       # 删除用户资料和用户-角色授权，优先读取 target_user_id
```

保存用户时，后端会把页面中的 `tenantRoles` 转换为 `auth_role_assignments`，并用 `AuthEnforcer.can_manage_role()` 校验当前操作者是否可授予目标角色。超级管理员可授予全局超管、机构管理员、机构操作员和自定义角色；机构管理员只能授予本机构可管理角色。

核心调用：

```python
allowed = enforcer.enforce(
    user_id="u_operator",
    tenant_id="tenant_huaxing",
    resource="metric:*",
    action="read",
    resource_attrs={
        "tenant_id": "tenant_huaxing",
        "resource_type": "metric",
        "metric_ids": {"m_balance"},
        "fields": {"branch_id", "metric_value"},
    },
)
```

指标动态过滤：

```python
decision = enforcer.metric_access(
    user_id="u_operator",
    tenant_id="tenant_huaxing",
    metric_ids={"m_balance", "m_loan"},
    requested_fields={"branch_id", "metric_value"},
)
```

返回值中包含：

- `allowed`: 是否允许查询。
- `allowed_metric_ids`: 可查询指标集合。
- `allowed_fields`: 可返回字段集合。
- `row_filter`: 应拼接到 SQL 或语义查询上下文中的行级过滤条件。

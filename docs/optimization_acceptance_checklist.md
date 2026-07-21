# 权限与架构优化验收清单

## 1. 权限管理

| 需求 | 当前实现 | 验收证据 |
|---|---|---|
| 超级管理员只有一个，不属于任何机构 | `backend/authz/rbac.py` 定义 `SUPER_ADMIN_ROLE_ID`，`build_default_rbac_seed()` 只创建一个 `tenant_id=None` 的超级管理员角色 | `backend.authz.tests.test_enforcer.test_default_rbac_has_single_global_super_admin` |
| 数据库层约束全局唯一超管 | `auth_roles` 要求 `role_level=100` 时 `tenant_id IS NULL`，并有 `uq_auth_roles_single_global_super_admin` 唯一索引 | `backend.platform.tests.test_schema_contracts.test_auth_schema_declares_global_super_admin_constraints` |
| 策略数据和鉴权模型分离 | `SQLitePolicyRepository` 可从 SQLite 加载角色、授权、策略和可管理角色，`AuthEnforcer` 不依赖内存对象 | `backend.authz.tests.test_enforcer.test_sqlite_policy_repository_matches_enforcer_contract` |
| 权限种子可重复执行且不破坏运行数据 | `SQLitePolicyRepository.seed()` 对角色、授权、策略和可管理角色做幂等写入，`build_local_platform(db_path=...)` 启动时不再清空权限表 | `test_sqlite_policy_seed_is_idempotent`、`test_sqlite_backed_platform_keeps_existing_authz_rows_on_rebuild` |
| 超管、机构管理员、机构操作员有层级关系 | `RoleLevel.SUPER_ADMIN=100`、`TENANT_ADMIN=50`、`OPERATOR=10`；`AuthEnforcer.can_manage_role()` 按层级和显式可管理清单判断 | `backend.authz.tests.test_enforcer.test_default_rbac_role_hierarchy_and_manageable_scope` |
| 机构管理员不能默认管理同级管理员 | `can_manage_role()` 已取消仅凭层级自动管理同级，只允许显式可管理角色或自己创建的非系统角色 | 同上 |
| 机构操作员不能管理角色 | 默认种子中操作员对 `role:* manage` 为 deny，且无 manageable role | 同上 |
| 菜单一级/二级选择规则 | `expand_menu_selection()` 支持一级带二级、二级带父级和自身；审计日志、系统配置默认可见 | `backend.authz.tests.test_enforcer` 菜单测试 |
| 左侧导航由权限模型驱动 | `/api/navigation` 按当前用户、机构逐项检查 `menu:<key>:read`，只返回允许菜单；前端 `Layout` 仍保留现有路径和图标，只按后端 `menu_keys` 过滤 | `test_http_navigation_is_filtered_by_menu_permissions`、`npm run build` |
| 用户管理接入后端授权闭环 | `backend/platform/access` 提供用户目录和用户-角色授权服务；`/api/access/users`、`/api/access/user` 支持查询、保存、删除用户，保存后写入 `auth_role_assignments` | `test_http_access_user_upsert_persists_profile_and_role_assignment` |
| 角色权限配置接入后端策略库 | `backend/platform/access` 提供机构角色权限查询和保存；`/api/access/role-policies`、`/api/access/role-policy` 将页面配置转换为 `auth_permission_policies` 和 `auth_manageable_roles` | `test_access_role_policy_save_rewrites_rbac_policies` |
| 指标行级/字段级 ABAC | `AuthEnforcer.metric_access()` 输出允许指标、允许字段和行过滤条件 | `backend.authz.tests.test_enforcer.test_metric_abac_fields_and_rows` |
| 查询层执行数据权限过滤 | `SemanticQueryService` 在调用语义查询前执行 `metric_access()`，并在返回结果后按允许指标、字段和行过滤条件过滤数据 | `test_metric_access_filters_authorized_metrics_before_query` |
| 角色权限页不在每个机构下展示超管 | `SystemSettings.tsx` 将超管移到“超级管理员管理全集”，机构卡片只展示机构管理员和机构操作员 | `npm run build` + 静态 grep |
| 当前超管的管理全集可见 | `RolePermissionView` 展示当前超管、机构数、菜单数、数据范围、可管理能力和可授权机构 | `SystemSettings.tsx` |

## 2. 架构优化

| 需求 | 当前实现 | 验收证据 |
|---|---|---|
| Skill 配置独立 | `configs/skills` + `SkillConfigCatalog` | `backend.platform.tests.test_agent_catalog.test_all_agent_allowed_skills_are_registered_in_skill_config` |
| 知识库独立 | `backend/platform/knowledge` | `backend.platform.tests.test_platform_workflow` |
| 记忆库独立 | `backend/platform/memory` | `backend.platform.tests.test_platform_workflow` |
| 知识/记忆可持久化 | `SQLiteKnowledgeStore` 和 `SQLiteMemoryStore` 在本地 API 模式下保存知识文档和运行记忆，记忆记录关联 trace | `test_sqlite_backed_platform_persists_tasks` |
| 指标字典租户化持久化 | `backend/platform/metrics` 提供 SQLite/内存仓储，`/api/metric-dictionary` 按 `tenant_id` 查询、初始化、保存和删除，指标名称按机构去重 | `test_http_metric_dictionary_is_tenant_scoped` |
| 系统接入配置租户化持久化 | `backend/platform/settings` 提供模型接入和数据接入仓储，`/api/system-config`、`/api/system-config/model`、`/api/system-config/data-connection` 支持按租户查询、保存和删除 | `test_http_system_config_is_tenant_scoped_and_masks_secrets` |
| 数据接入密钥不回传明文 | 数据连接保存后，接口返回和查询结果中的 `password` 均为 `******`，避免前端持有明文密钥 | `test_http_system_config_is_tenant_scoped_and_masks_secrets` |
| 数据接入密钥不明文落库 | `backend/platform/security/secrets.py` 提供本地 secret codec，SQLite `secret_value` 存储 `enc:v1:` 编码值 | `test_sqlite_system_config_encrypts_data_connection_secret_at_rest` |
| 数据接入配置可验证可调用 | `backend/platform/settings/connection_test.py` 通过 `build_data_warehouse_from_env()` 匹配数据集目录并执行样例查询，`/api/system-config/data-connection/test` 返回可调用状态、匹配数据集和样例数据 | `test_http_system_config_is_tenant_scoped_and_masks_secrets` + 浏览器点击“测试”冒烟 |
| 每个目标 URL 独立维护爬虫 | 同一机构可保存多个连接；每条记录只对应一个目标 URL，后端生成稳定 `crawlerKey`，会话状态按租户和 URL 隔离 | `test_each_registered_url_has_a_stable_crawler_identity`、`test_same_institution_can_register_multiple_page_connections`、前端权限冒烟 |
| 页面型与 SQL 页面型爬虫分离 | `crawlerMode=page` 遍历页面筛选并采集页面/API 数据；`crawlerMode=sql` 只执行单条只读 `SELECT/WITH`，元数据也由页面爬取 | `test_sql_page_crawler_requires_readonly_sql_for_data_query`、`test_sql_decomposition_rejects_write_multi_statement_and_dangerous_function` |
| 验证码会话合规复用 | 首次人工完成验证码、短信或 MFA，状态文件按租户和 URL 保存为 `0600`；失效后重新人工验证，不实现验证码绕过 | `test_url_crawler_session_state_is_isolated_by_tenant_and_url` |
| 知识文件与数据资产定时提炼为记忆 | LLM 模式一次收集知识文件、原始表和主题表并只调用一次模型；脚本模式不调用模型、不显示 Prompt；知识文件不能直接作为 Skill 记忆 | `test_llm_mode_accepts_knowledge_files_and_data_assets_in_one_call`、`test_script_mode_never_calls_model`、`test_skill_runtime_never_resolves_knowledge_file_as_memory` |
| 记忆模块统一使用一个模型配置 | `memory_extraction` 应用模块保存新绑定时只释放该模块旧绑定，不影响其他允许多模型的应用模块 | `test_memory_module_has_one_current_binding_in_memory_store`、`test_memory_module_has_one_current_binding_in_sqlite_store` |
| 无外部库/数仓时可通过 JSON mock 仓运行 | `data/mock/semantic_datasets.json` + `JSONDataWarehouse` 提供租户安全数据源，语义本地适配器从 JSON 聚合而不是代码硬编码样例 | `test_json_mock_warehouse_executes_tenant_scoped_aggregation`、`test_analysis_uses_governed_skill_and_semantic_layer` |
| 数据层具备数据库/数仓适配边界 | `SQLDataWarehouse` 通过 DB-API 连接工厂接入 SQLite/PostgreSQL/数仓驱动，数据集、指标、维度和表名均来自目录白名单，租户和筛选值参数化传入 | `test_sql_data_warehouse_executes_tenant_scoped_query` |
| 语义运行链路可配置切换数据仓库 | `build_data_warehouse_from_env()` 默认装配 JSON mock，设置 `SMART_DATA_AGENT_DATA_WAREHOUSE=sqlite` 后通过 SQLite/DB-API 仓库跑完整 `run_analysis`，健康检查同步暴露 `data_source_mode` | `test_sqlite_configured_warehouse_runs_through_semantic_workflow` |
| MCP 独立网关 | `backend/platform/mcp`，调用前权限检查，结果脱敏 | `test_mcp_gateway_sanitizes_results_and_checks_permission` |
| MCP 可从配置装载并 mock 外部系统 | `configs/mcp_servers` 配置 database/knowledge MCP，`backend/platform/mcp/registry.py` 注册 JSON 数仓和知识库 mock handlers | `test_local_mcp_registry_loads_configured_mock_servers` |
| MCP 统一 API 可对接外部系统 | `/api/mcp/servers`、`/api/mcp/tools`、`/api/mcp/call` 提供服务器发现、工具发现和受治理调用，调用仍走 RBAC 权限和输出脱敏 | `test_http_mcp_api_lists_and_calls_mock_tools` |
| Agent 协作与编排 | `backend/platform/orchestration` + `AnalysisWorkflow` | `test_analysis_uses_governed_skill_and_semantic_layer` |
| 本轮分析思路进入编排链路 | `AnalysisWorkflow` 根据问题生成 dataset、metrics、dimensions、chart_types 和业务分析角度 | `test_diagnostic_question_builds_risk_analysis_plan` |
| SuperSonic 不由 Agent 直接写 SQL | `supersonic.query` Skill 统一调用 `SemanticQueryService`；`SupersonicHTTPClient` 可接远程语义服务，本地适配器只允许白名单指标/维度/数据集，并输出参数化 SQL 形态 | `test_analysis_uses_governed_skill_and_semantic_layer`、`test_supersonic_http_client_translates_remote_response` |
| 远程语义服务失败可降级 | `FallbackSupersonicClient` 远程失败时回落到本地语义适配器，并在 `semantic_info` 中记录 fallback 原因 | `test_supersonic_client_falls_back_to_local_when_remote_fails` |
| SQL 结果进入受控 Python 可视化边界 | `backend/platform/data_processing/PythonSandbox` 只允许 `build_chart(data, context)` 声明式脚本，`AnalysisWorkflow` 在语义查询后生成 `python_script` 和 `visualization_artifact`，再基于数据形成总结 | `test_python_sandbox_executes_controlled_visualization_script`、`test_analysis_uses_governed_skill_and_semantic_layer` |
| 分析任务可持久化追踪 | `AnalysisTaskRepository` 保存任务、计划、结果、结论、复核结果和 trace | `test_sqlite_backed_platform_persists_tasks` |
| 请求级运行健康可观测 | `RuntimeEvent` 记录分析请求成功/失败、耗时和 fallback 状态，`/api/health` 返回运行摘要 | `test_analysis_uses_governed_skill_and_semantic_layer`、`test_skill_permission_is_checked_before_query`、`test_analysis_runtime_summary_counts_fallback` |
| 监控系统可采集指标 | `/api/metrics` 输出 Prometheus 风格请求数、fallback 数、平均耗时和样本数 | `test_http_api_runs_analysis` |
| 质量监控页展示真实运行健康 | `src/app/services/systemHealthApi.ts` 读取 `/api/health`，`DataAssets` 质量监控页展示服务状态、语义层模式、样本数、错误/降级和耗时 | `npm run build` + `curl -s http://127.0.0.1:8787/api/health` |
| 接口层统一目录可被外部系统发现 | `backend/platform/api/router.py` 注册当前所有公开 API，`/api/routes` 返回机器可读路由清单，`/api/health` 返回 `route_count` | `test_http_api_runs_analysis` |
| API 请求输入有防护 | 非法 JSON 返回 `400 invalid_json`，请求体过大返回 `413 request_body_too_large` | `test_http_api_rejects_invalid_or_oversized_json` |
| API 身份上下文可切换严格模式 | `backend/platform/security` 提供签名 session token；`SMART_DATA_AGENT_AUTH_MODE=strict` 时受保护接口只信任 Bearer token，忽略 body/query 中的 `user_id` 和 `tenant_id` | `test_http_api_strict_auth_requires_signed_token`、`test_http_api_strict_auth_uses_signed_context_over_body_spoofing` |
| 导航权限 API 可复用 | `backend/platform/navigation.py` 基于 `MENU_TREE` 和 `PermissionBroker` 生成可见菜单树，父级菜单因子菜单可见而保留，避免前端硬编码权限 | `test_http_navigation_is_filtered_by_menu_permissions` |
| 自助分析页面接入后端链路 | `src/app/services/analysisApi.ts` 调用 `/api/analysis/run`，`SelfAnalysis` 将后端计划、SQL、数据和结论映射到现有页面结构，失败时显示明确错误和空状态，不再静默渲染伪分析结果 | `npm run build` + `/api/analysis/run` 代理冒烟验证 |
| 自助分析结果保存接入周报后端 | `backend/platform/reports` 提供保存分析结果仓储，`/api/reports/analysis-results`、`/api/reports/analysis-result` 支持周报引用分析结果；前端 `reportApi.ts` 统一调用 | `test_http_report_analysis_results_are_tenant_scoped`、`npm run build` |
| 周报评论接入后端持久化 | `backend/platform/reports` 提供报告评论快照仓储，`/api/reports/comments` 支持读取和替换评论数组；周报页面保留现有评论气泡、下划线、追评交互 | `test_http_report_comments_are_persisted_by_report`、`npm run build` |
| 周报核心指标与模块管理 | 核心指标固定菜单首位，默认展示在贷余额、放款金额、新增余额及柱线组合图；其他已保存分析显示分析时间，可拖动排序并点击显隐 | `scripts/frontend-permission-smoke.mjs` 周报模块冒烟、`npm run build` |
| 周报打开后自动分析并可由编辑打断 | 页面打开仅触发一次核心指标分析；分析中显示“正在分析”，用户编辑会递增修订号、取消运行并阻止迟到结果写回；重新生成携带行为记忆、描述性分析 Skill、固定数据源和格式契约 | `WeeklyReport.tsx` 自动分析与修订门禁、前端权限冒烟、`npm run build` |
| 周报正文图片富文本交互 | 第二、三、四部分支持从剪贴板上传图片、按光标拆分段落、点击图片上下间隙插入空白段落、右上角/右下角同时调整宽高，图片使用轻圆角 | `WeeklyReport.tsx` 富文本编辑器契约、`npm run typecheck`、`npm run build` |
| 机构选择进入租户上下文 | `Layout` 的机构选择通过 `tenantIdFromInstitution()` 转为 `tenant:机构名称`，`SelfAnalysis` 请求携带 `tenant_id`，本地平台种子为运营机构授权 `supersonic.query` | `test_operating_tenant_context_is_authorized_and_persisted` + `run_analysis(... tenant:华兴银行 ...)` 冒烟验证 |
| 指标管理页面接入后端租户字典 | `src/app/services/metricDictionaryApi.ts` 调用 `/api/metric-dictionary`，`DataAssets` 首次为空时按当前机构初始化指标全集，后续新增/修改/删除同步后端，失败时本地降级 | `npm run build` + `PUT/GET/DELETE /api/metric-dictionary` 冒烟验证 |
| 系统配置页面接入后端配置仓储 | `src/app/services/systemConfigApi.ts` 调用 `/api/system-config`，`SystemSettings` 的模型接入、数据接入优先使用后端，新增/删除同步后端，失败时保留本地降级 | `npm run build` + `POST/GET/DELETE /api/system-config/*` 冒烟验证 |
| 审计日志接入后端事件流 | `backend/platform/audit` 提供内存/SQLite 审计仓储，系统配置、用户授权、角色权限、指标字典等关键写操作写入审计事件，`/api/audit-logs` 按租户查询，前端审计日志页优先展示后端事件 | `test_http_system_config_is_tenant_scoped_and_masks_secrets`、`npm run build`、Playwright 审计页冒烟 |
| 本地 HTTP API 可运行 | `backend/platform/api/server.py` 提供 `/api/health` 和 `/api/analysis/run`，健康检查返回 `semantic_client_mode` | `test_http_api_runs_analysis` + `curl -s http://localhost:5173/api/health` |
| API 请求上下文集中解析 | `/api/analysis/run`、`/api/metric-dictionary`、`/api/system-config` 统一通过 `APIRequestContext` 和 `backend/platform/security` 解析用户和租户；开发模式支持 Header 兼容，严格模式使用签名 token | `test_http_api_runs_analysis`、严格模式认证测试 |
| 中文机构上下文可稳定传输 | 前端开发态 `X-Tenant-Id` 使用 `encodeURIComponent` 编码，后端 `resolve_request_context()` 统一解码，避免中文机构名触发 header 字符集问题；严格模式继续使用 ASCII Bearer token | `test_http_access_user_upsert_persists_profile_and_role_assignment`、`npm run build` |
| 前端页面按路由拆分 | `src/app/routes.ts` 使用 React lazy/Suspense，避免所有页面同步进入首包 | `npm run build` 输出主入口约 256KB 且无 500KB chunk 警告 |
| 工程开发 Agent 组落地 | `configs/agent_groups/engineering.json` | `test_loads_engineering_and_algorithm_groups` |
| 算法工程师 Agent 组落地 | `configs/agent_groups/algorithm.json` | `test_loads_engineering_and_algorithm_groups` |
| 工程/算法门禁防 demo 化 | Agent Group `stage_gates` 明确数据库、后端、权限、测试、风控合规、漂移监控等门禁 | `test_agent_group_stage_gates_prevent_demo_delivery` |
| 平台表结构支持 Agent/Skill/MCP/Knowledge/Memory/Audit/Eval | `backend/platform/schema.sql` | `test_platform_schema_declares_agent_group_and_eval_tables` |

## 3. 当前验证命令

```bash
python3 -m unittest discover backend
npm run build
curl -s http://localhost:5173/api/health
curl -s http://localhost:5173/api/metrics
npm run dev:api
npm run dev
```

通过标准：

- 后端测试全部通过。
- 前端构建通过。
- 旧双周报子项目目录不存在且无代码残留引用。
- 系统管理角色权限页中，“超级管理员”只作为全局管理全集展示，不再作为每个机构权限卡片的一列。

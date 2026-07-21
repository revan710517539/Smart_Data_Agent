# 114 项实现与自动化验收证据

更新时间：2026-07-10。本文件逐项保留 114 个原始编号，不合并、不删除。详细目标仍以 issue_registry.md 为准。

## 总体验收基线

- 生产 schema catalog 生成 99 张 PostgreSQL 表，每张表均有 docs/database_tables/<table>.md 独立文档。
- 全新 PostgreSQL 17 完成空库迁移、幂等重跑、显式租户/用户/RBAC 初始化；核心生产 Store 集成 2/2 通过。
- 后端全量 206/206 通过；真实 PostgreSQL 覆盖 100 次并发读突发、任务 claim、市场告警 cooldown 和首次状态写入并发。
- 前端 TypeScript、Vite production build、权限 smoke、核心组件 3000 行门禁通过；页面视觉和主要交互未重设计。
- npm audit 与 pip-audit 均报告 0 个已知漏洞；schema drift 与 Python compileall 通过。

## 逐项证据

| 编号 | 原问题 | 验收目标 | 主要实现证据 | 自动化验收 |
|---|---|---|---|---|
| A01 | 三条执行路径没有统一事实源 | 所有计划、查询、产物、结论和评审归属同一 execution_id | backend/platform/orchestration/workflow.py; backend/platform/postgresql_repository.py | test_semantic_execution_correctness.py |
| A02 | 30 个 Agent 仅为配置目录 | AgentSpec 能被真实加载、执行、授权和追踪 | backend/platform/agents/; backend/platform/skills/; backend/platform/mcp/; backend/platform/orchestration/workflow.py | test_agent_catalog.py; test_agent_skill_mcp_governance.py; test_capability_approvals.py |
| A03 | Agent Group 门禁未进入运行流程 | stage/review gate 编译为可恢复状态机 | backend/platform/agents/; backend/platform/skills/; backend/platform/mcp/; backend/platform/orchestration/workflow.py | test_agent_catalog.py; test_agent_skill_mcp_governance.py; test_capability_approvals.py |
| A04 | 41 个 Skill 仅 1 个有运行 handler | Skill 明确 configured/implemented/healthy/disabled 状态 | backend/platform/skills/registry.py; backend/platform/api/routes/capabilities.py | test_agent_skill_mcp_governance.py::test_configured_skills_are_not_misreported_as_implemented |
| A05 | Skill 风险、权限、超时、重试和版本未执行 | Executor 强制 schema、权限、超时、重试、配额和审批 | backend/platform/skills/executor.py; backend/platform/governance/postgresql_approvals.py | test_capability_approvals.py |
| A06 | MCP endpoint 无真实 transport，数据库 MCP 固定 Mock | 标准 MCP transport 使用当前授权 Warehouse | backend/platform/api/routes/mcp.py; backend/platform/mcp/registry.py | test_platform_workflow.py MCP Streamable HTTP cases |
| A07 | MCP allowed_agents 被忽略，未知工具返回 mocked | 用户、Agent、工具、数据域全校验且未知工具 fail closed | backend/platform/mcp/gateway.py | test_agent_skill_mcp_governance.py |
| A08 | 模型、Prompt 与系统配置割裂 | 统一模型注册、密钥、路由、Prompt 版本和调用审计 | backend/platform/llm/registry.py; backend/platform/settings/postgresql_store.py | test_platform_workflow.py model audit cases; test_egress_security.py |
| A09 | 图谱只有数据类，没有真实血缘 | 指标到字段、数据集、报告和结论可双向追踪 | backend/platform/lineage/postgresql_store.py; backend/platform/orchestration/workflow.py | test_lineage.py; PostgreSQL integration |
| A10 | Agent/Skill/MCP/Evaluation 声明与运行库分叉 | Schema catalog、迁移和逐表文档来自同一事实源 | backend/platform/database/schema_catalog.py; scripts/generate_database_schema.py | test_schema_contracts.py |
| B01 | 展示 SQL 与实际执行 SQL 不一致 | 新执行 0 不一致，历史记录有迁移/标记，SQL hash 一致 | backend/platform/semantic/; backend/platform/orchestration/; backend/platform/metrics/semantics.py; backend/platform/postgresql_repository.py | test_semantic_execution_correctness.py |
| B02 | Workflow 与 IntelligentAnalysisEngine 是两条链 | plan→compile→execute→visualize→conclude→review 单链路 | backend/platform/semantic/; backend/platform/orchestration/; backend/platform/metrics/semantics.py; backend/platform/postgresql_repository.py | test_semantic_execution_correctness.py |
| B03 | 页面 Python 与真实执行脚本不一致 | 执行脚本与 hash 可追溯，候选脚本显式标记未执行 | backend/platform/semantic/; backend/platform/orchestration/; backend/platform/metrics/semantics.py; backend/platform/postgresql_repository.py | test_semantic_execution_correctness.py |
| B04 | Review 发生在最终结果形成之前 | Review 对最终证据包执行，失败不能标成功 | backend/platform/semantic/; backend/platform/orchestration/; backend/platform/metrics/semantics.py; backend/platform/postgresql_repository.py | test_semantic_execution_correctness.py |
| B05 | 前端按行号编造经营指标 | 缺失字段只显示不可用，源代码和浏览器均无推导逻辑 | backend/platform/operating_snapshots/service.py; governed frontend snapshots | test_operating_snapshots.py; frontend-permission-smoke.mjs |
| B06 | 多指标计划只执行第一个指标 | 同粒度多指标或多查询主键合并均有正确性测试 | backend/platform/semantic/query_service.py; backend/platform/data_access/sql_warehouse.py | test_semantic_execution_correctness.py matrix cases |
| B07 | 多维计划只执行第一个维度 | 多维聚合、下钻和粒度校验真实生效 | backend/platform/semantic/query_service.py; backend/platform/data_access/sql_warehouse.py | test_semantic_execution_correctness.py matrix cases |
| B08 | 时间、TopN、排序过滤未解析 | 类型化条件进入执行计划、参数和 SQL | backend/platform/orchestration/query_conditions.py | test_semantic_execution_correctness.py::test_query_conditions_compile_time_topn_and_sort |
| B09 | 率指标错误使用 AVG 和 SUM | 指标版本保存分子分母和 aggregation semantics | backend/platform/metrics/semantics.py; backend/platform/data_access/sql_warehouse.py | test_semantic_execution_correctness.py ratio-of-sums cases |
| B10 | 前 20 行被误称总体合计 | 独立总计查询与分页明细，结论只引用完整汇总 | backend/platform/data_access/sql_warehouse.py | test_semantic_execution_correctness.py separate total/full count cases |
| B11 | LLM 不接收真实查询证据 | Prompt 仅引用裁剪脱敏的已执行结果和 evidence_id | backend/platform/semantic/; backend/platform/orchestration/; backend/platform/metrics/semantics.py; backend/platform/postgresql_repository.py | test_semantic_execution_correctness.py |
| B12 | 可能结论为固定模板 | 每条结论引用指标、维度、值、时间和快照 | backend/platform/semantic/; backend/platform/orchestration/; backend/platform/metrics/semantics.py; backend/platform/postgresql_repository.py | test_semantic_execution_correctness.py |
| B13 | Demo key/真实模型失败仍可能成功 | mock/real/degraded/failed 状态不可混淆 | backend/platform/settings/model_test.py; backend/platform/runtime_config.py | test_egress_security.py; test_runtime_config.py |
| B14 | 人工修改计划、SQL、Python 后重跑被忽略 | 指定 revision 被真实编译执行并产生新 execution | backend/platform/api/routes/analysis.py; backend/platform/repository.py | test_semantic_execution_correctness.py manual revision cases |
| B15 | 未验证主题表 SQL 被称为 Verified | 语法、权限、租户条件、列和样例结果全部校验 | backend/platform/security/sql_validation.py; backend/platform/assets/store.py | test_data_asset_truth.py |
| B16 | SQL 标识符拼接缺少 catalog 校验 | 只允许已授权元数据标识符，禁止任意前端标识符 | backend/platform/security/sql_validation.py; backend/platform/data_access/ | test_semantic_execution_correctness.py unsafe identifier/SQL cases |
| B17 | 指标字典未进入语义计划和 SQL | 可执行 semantic model 解析公式、单位、粒度和来源 | backend/platform/semantic/; backend/platform/orchestration/; backend/platform/metrics/semantics.py; backend/platform/postgresql_repository.py | test_semantic_execution_correctness.py |
| B18 | 行列权限在查询后过滤 | tenant/row/field/metric ACL 下推到数据源 | backend/platform/semantic/configured_client.py; backend/platform/governance/permission_broker.py | test_configured_connection_semantic.py |
| B19 | 空集合、缺字段、图表字段存在 ACL 绕过 | 缺少权限字段直接拒绝，空集合返回零行 | backend/platform/semantic/configured_client.py; backend/platform/data_access/sql_warehouse.py | test_semantic_execution_correctness.py empty-filter and ACL cases |
| B20 | 缺少新鲜度、分区、快照、版本和事实一致性 | immutable Evidence Bundle 成为报告发布门禁 | backend/platform/ingestion/postgresql_store.py; backend/platform/reports/postgresql_store.py | test_data_acquisition.py; test_report_integrity.py |
| C01 | 所有租户默认读取相同 JSON Mock | Demo 环境隔离，生产和发布流程拒绝 Mock | backend/platform/runtime_config.py; backend/platform/data_access/factory.py | test_runtime_config.py; test_data_asset_truth.py |
| C02 | 页面保存的数据连接未进入分析运行时 | 执行按授权 connection_id/version 创建连接 | backend/platform/semantic/configured_client.py; backend/platform/settings/postgresql_store.py | test_configured_connection_semantic.py |
| C03 | 连接测试忽略用户填写的连接信息 | 按 source type 真实认证、catalog 和 sample query | backend/platform/settings/connection_test.py | test_egress_security.py data-connection case |
| C04 | 启用连接即标 connected | draft→testing→verified→degraded/disabled 状态机 | backend/platform/ingestion/; backend/platform/assets/; backend/platform/knowledge/; backend/platform/memory/ | test_data_acquisition.py; test_data_asset_truth.py; test_knowledge_lifecycle.py; test_memory_lifecycle.py |
| C05 | SQL Warehouse 只支持环境 SQLite 和单一方言 | PostgreSQL、Doris/Hive、QBI/API、CSV/对象存储适配器 | backend/platform/data_access/postgresql_warehouse.py; doris_warehouse.py; hive_warehouse.py; http_source.py; csv_warehouse.py | test_semantic_execution_correctness.py adapter cases |
| C06 | 缺少数据获取脚本、实时/离线流和修复流程 | Script Version、Job、Run、Artifact、Failure、Repair Proposal 闭环 | backend/platform/ingestion/service.py; backend/platform/ingestion/postgresql_store.py | test_data_acquisition.py; PostgreSQL integration |
| C07 | 缺少元数据、CSV 索引和 latest artifact 查询 | 支持 getLatestCsvByTopicTable(topic_table_id, org_id) 等稳定接口 | backend/platform/api/routes/acquisition.py; backend/platform/ingestion/postgresql_store.py | test_data_acquisition.py latest CSV case |
| C08 | 读路径混入代码默认数据 | 初始化显式 seed，查询只返回持久化事实 | backend/platform/bootstrap.py; scripts/provision_production.py | test_data_asset_truth.py; restart/seed tests |
| C09 | 数据资产缺少严格 schema、引用和审批 | 每类资产有 schema、FK、版本和审批状态 | backend/platform/ingestion/; backend/platform/assets/; backend/platform/knowledge/; backend/platform/memory/ | test_data_acquisition.py; test_data_asset_truth.py; test_knowledge_lifecycle.py; test_memory_lifecycle.py |
| C10 | 三套知识/附件系统互不相通 | 统一 Document/Version/Chunk/Attachment/Citation | backend/platform/ingestion/; backend/platform/assets/; backend/platform/knowledge/; backend/platform/memory/ | test_data_acquisition.py; test_data_asset_truth.py; test_knowledge_lifecycle.py; test_memory_lifecycle.py |
| C11 | 上传文件未真实保存、解析或索引 | 对象存储、病毒扫描、OCR、分块、索引和状态 | backend/platform/knowledge/files.py; backend/platform/ingestion/artifacts.py | test_knowledge_lifecycle.py; test_artifact_object_store.py |
| C12 | 文件正文重复进入 action/audit/task | 审计仅存 ID/hash/分类，不复制正文 | backend/platform/audit/store.py; backend/platform/application/store.py | test_audit_security.py |
| C13 | 子串检索弱且 doc_id 可跨租户覆盖 | tenant UUID、所有权、混合检索、重排和引用 | backend/platform/ingestion/; backend/platform/assets/; backend/platform/knowledge/; backend/platform/memory/ | test_data_acquisition.py; test_data_asset_truth.py; test_knowledge_lifecycle.py; test_memory_lifecycle.py |
| C14 | 记忆只写不读且无生命周期 | Candidate→Review→Active→Superseded/Expired，并进入规划 | backend/platform/memory/service.py; backend/platform/memory/postgresql_store.py | test_memory_lifecycle.py; PostgreSQL integration |
| D01 | 声明 schema 与真实运行表不一致 | 迁移和 schema catalog 成为唯一结构事实源 | backend/platform/database/schema_catalog.py; scripts/generate_database_schema.py | test_schema_contracts.py schema/doc drift |
| D02 | user_version=0 且无迁移历史 | 空库/旧库迁移、幂等和 checksum 漂移测试通过 | backend/platform/database/migrator.py; scripts/migrate_postgresql.py | test_schema_contracts.py rollback/drift; real PostgreSQL empty/idempotent migration |
| D03 | Store 启动时自行 CREATE/ALTER | Store 无 DDL，结构只由迁移创建 | backend/platform/database migrations; stores contain no startup DDL | test_schema_contracts.py::test_sqlite_bootstrap_uses_migrations_instead_of_store_ddl |
| D04 | 核心表缺少租户、用户和业务外键 | 逐表 FK、删除策略和跨租户约束完整 | backend/platform/database/schema_catalog.py; backend/platform/*/postgresql_store.py; docs/database_tables/ | test_schema_contracts.py; test_postgresql_runtime.py; test_postgresql_stores_integration.py |
| D05 | 核心业务对象大量整块 JSON | 可查询字段规范化，仅扩展属性使用 JSONB | backend/platform/database/schema_catalog.py; backend/platform/*/postgresql_store.py; docs/database_tables/ | test_schema_contracts.py; test_postgresql_runtime.py; test_postgresql_stores_integration.py |
| D06 | 独立列与 JSON payload 双写漂移 | 单一主字段来源或数据库一致性约束 | backend/platform/database/schema_catalog.py; backend/platform/*/postgresql_store.py; docs/database_tables/ | test_schema_contracts.py; test_postgresql_runtime.py; test_postgresql_stores_integration.py |
| D07 | 状态、范围和 JSON 缺少 CHECK | 枚举、范围、JSON 类型和业务约束入库 | backend/platform/database/schema_catalog.py; backend/platform/*/postgresql_store.py; docs/database_tables/ | test_schema_contracts.py; test_postgresql_runtime.py; test_postgresql_stores_integration.py |
| D08 | 整块覆盖导致并发丢更新 | 行级实体、PATCH、lock_version/ETag | PostgreSQL stores use FOR UPDATE, advisory locks, lock_version and expected revision | test_report_integrity.py; test_automation_runtime.py; PostgreSQL concurrency integration |
| D09 | 写接口无幂等键 | 生成、发送、触发、保存均支持幂等去重 | analysis/acquisition/automation/report idempotency keys and unique constraints | test_automation_runtime.py; test_report_integrity.py; test_data_acquisition.py |
| D10 | 时间字段格式混乱 | 数据库统一 timestamptz UTC，展示层本地化 | backend/platform/database/schema_catalog.py; backend/platform/*/postgresql_store.py; docs/database_tables/ | test_schema_contracts.py; test_postgresql_runtime.py; test_postgresql_stores_integration.py |
| D11 | 机构是静态字符串而非主数据 | Tenant/OrgUnit 稳定 ID、层级、编码和生效状态 | backend/platform/database/schema_catalog.py; backend/platform/*/postgresql_store.py; docs/database_tables/ | test_schema_contracts.py; test_postgresql_runtime.py; test_postgresql_stores_integration.py |
| D12 | ID、作者、状态和时间可由客户端伪造 | 服务端生成并验证状态迁移 | backend/platform/database/schema_catalog.py; backend/platform/*/postgresql_store.py; docs/database_tables/ | test_schema_contracts.py; test_postgresql_runtime.py; test_postgresql_stores_integration.py |
| D13 | 单进程打开大量独立 SQLite 连接 | 本地连接管理；生产 PostgreSQL pool | backend/platform/database/postgresql.py shared pool | test_postgresql_runtime.py; PostgreSQL 100-read burst |
| D14 | SQLite/WAL 不适合多实例并发 | 生产 PostgreSQL，开发库有 checkpoint/backup/vacuum | production PostgreSQL composition; backend/platform/database/sqlite_maintenance.py | test_postgresql_runtime.py; test_local_concurrency.py |
| D15 | 无归档、保留、PITR、软删和分页索引 | 生命周期、PITR、append-only audit 和索引基线 | backend/platform/reports/retention.py; docs/production_upgrade/operations_runbook.md | test_report_retention.py |
| E01 | 已知邮箱即可登录 | OIDC/SAML/企业 IdP 或至少密码/OTP | backend/platform/security/oidc.py; backend/platform/api/routes/auth.py | test_oidc_security.py; strict-auth tests |
| E02 | strict 模式仍允许邮箱登录 | strict 仅接受可信身份源且禁匿名注册 | backend/platform/api/routes/auth.py; backend/platform/runtime_config.py | test_platform_workflow.py strict login/register cases |
| E03 | 注册可自选机构并获得角色 | 邀请、员工校验或管理员审批 | scripts/provision_production.py; backend/platform/access/ | access-control integration tests |
| E04 | development 身份头默认可信 | 仅 loopback 显式开启，生产默认 strict | backend/platform/security/session.py; backend/platform/runtime_config.py | test_platform_workflow.py strict identity-header cases |
| E05 | 重启重新插入默认角色和授权 | 撤销角色/权限、删除账号后重启均不恢复 | backend/platform/bootstrap.py; scripts/provision_production.py | test_platform_workflow.py revoked-role restart cases |
| E06 | 超级管理员身份硬编码且前端可升级会话 | 权限仅以后端 claims 为准 | backend/authz/; backend/platform/security/; backend/platform/governance/; backend/platform/api/support.py | test_enforcer.py; test_oidc_security.py; test_session_security.py; test_egress_security.py; test_rate_limits.py |
| E07 | Token 存 localStorage | HttpOnly/Secure/SameSite 会话 Cookie | backend/platform/security/session.py; auth routes use HttpOnly/Secure/SameSite cookies | test_session_security.py |
| E08 | Token 无标准会话、撤销和轮换 | issuer/audience/jti/kid、refresh、revocation、device session | backend/platform/security/session.py; backend/platform/security/postgresql.py | test_session_security.py; PostgreSQL integration |
| E09 | 页面会话策略不进入认证运行时 | idle/absolute/refresh timeout 真正生效 | backend/platform/security/session.py | test_session_security.py idle/absolute/access expiry cases |
| E10 | CORS=* 且本机身份头可被网页调用 | Origin/Host allowlist 和身份头禁用 | backend/platform/runtime_config.py; backend/platform/api/asgi.py | test_runtime_config.py; test_asgi_runtime.py |
| E11 | WebSocket query token 泄露风险 | Cookie 或一次性短期 ticket | backend/platform/api/asgi.py WebSocket Cookie/subprotocol boundary | test_asgi_runtime.py |
| E12 | 无登录、分析、模型、MCP、上传限流 | user/tenant/IP/provider 多维限流和预算 | backend/platform/security/rate_limit.py; backend/platform/api/support.py | test_rate_limits.py |
| E13 | 无 TLS、安全头、WS Origin/大小/时长限制 | 网关/ASGI 强制 TLS 和资源限制 | backend/platform/api/asgi.py; security headers in server.py | test_asgi_runtime.py |
| E14 | 用户 URL 测试存在 SSRF | allowlist、DNS/IP 校验和受控 egress | backend/platform/security/egress.py | test_egress_security.py |
| E15 | 自制密钥封装且有默认开发 key | KMS/Vault envelope encryption 与 key version | backend/platform/security/secrets.py; backend/platform/runtime_config.py | test_runtime_config.py; KMS round-trip test |
| E16 | Action/Audit 保存完整敏感 payload | 字段级审计、脱敏、摘要 hash 和数据分类 | backend/platform/audit/store.py | test_audit_security.py |
| E17 | str(exc) 直接返回客户端 | 稳定错误码/request_id，详情仅内部日志 | backend/platform/api/support.py; backend/platform/observability/trace.py | test_trace_telemetry.py; stable API error tests |
| E18 | 页面数据范围未落实行列指标权限 | org/metric/field/row scope 编译并下推 | backend/platform/governance/permission_broker.py; backend/platform/semantic/configured_client.py | test_enforcer.py; test_configured_connection_semantic.py |
| E19 | Todo/Task 缺少所有者对象级授权 | owner/assignee ACL 覆盖查改删 | backend/platform/application/postgresql_store.py; backend/platform/automation/postgresql_store.py | test_object_authorization.py; PostgreSQL integration |
| E20 | 菜单隐藏不等于路由授权，报告无个人范围 | 路由 guard 与 owner/shared scope | API route guards; backend/platform/reports/postgresql_store.py owner/shared scope | navigation/report authorization tests |
| F01 | 管理驾驶舱静态指标 | 接统一查询服务和指标快照 | backend/platform/operating_snapshots/service.py; src/app/components/Dashboard.tsx | test_operating_snapshots.py |
| F02 | 业务漏斗静态数组 | 漏斗定义、事实表和转化口径 | backend/platform/operating_snapshots/service.py; src/app/components/BusinessFunnel.tsx | test_operating_snapshots.py |
| F03 | 经营沙盘使用固定常数公式 | 模型版本、校准数据、范围、置信区间 | src/app/components/BusinessSandbox.tsx; backend/platform/application/store.py fail-closed model gate | production typecheck/build; unavailable-action regression |
| F04 | 客群分析静态数据 | 画像主题表和分群版本 | backend/platform/operating_snapshots/service.py; src/app/components/CustomerInsight.tsx | test_operating_snapshots.py |
| F05 | 竞品分析无来源证据 | 市场来源、采集时间、证据和对比口径 | backend/platform/market/; src/app/components/CompetitionAnalysis.tsx | test_market_monitoring.py; PostgreSQL integration |
| F06 | 机构督导静态数组 | 组织、目标、实绩、问题和督导任务 | backend/platform/operating_snapshots/service.py; src/app/components/InstitutionSupervision.tsx | test_operating_snapshots.py |
| F07 | 邮件日报仅改 sent 状态 | 正文、队列、provider id、送达和失败回执 | backend/platform/reports/daily_email.py; backend/platform/automation/runtime.py | test_daily_email_delivery.py; test_automation_runtime.py |
| F08 | 推送与订阅为静态数组 | 规则、订阅、事件和真实 Delivery Adapter | backend/platform/automation/postgresql_store.py; backend/platform/market/postgresql_store.py | test_automation_runtime.py; test_market_monitoring.py |
| F09 | 自动化任务没有调度与 Worker | trigger/run/lease/retry/checkpoint/cancel | backend/platform/automation/runtime.py; backend/platform/automation/postgresql_store.py | test_automation_runtime.py; concurrent claim integration |
| F10 | 任务运行状态可由客户端填写 | 仅 Worker 状态机可推进 | backend/platform/automation/runtime.py worker-owned transitions | test_automation_runtime.py terminal-state cases |
| F11 | 加载 Skill 只增加名称 | 安装、签名、版本、依赖、健康和执行 | backend/platform/skills/; backend/platform/api/routes/capabilities.py | test_agent_skill_mcp_governance.py |
| F12 | 导出只返回文件名或基于伪数据 CSV | 真实 artifact、hash、下载授权和过期时间 | backend/platform/ingestion/artifacts.py; authorized acquisition/attachment content routes | test_artifact_object_store.py; test_data_acquisition.py; test_knowledge_lifecycle.py |
| F13 | 未识别通用动作也返回成功 | 未注册动作 4xx，注册动作有 handler 和结果 | backend/platform/application/store.py; backend/platform/api/routes/application.py | test_http_application_action_does_not_fake_unimplemented_agent_success |
| F14 | 右下角 Agent 失败时返回硬编码数字 | 真实状态、证据和明确失败/降级 | backend/platform/application/store.py fail-closed agent action; real evidence states | application/analysis HTTP regressions |
| F15 | 周报初始数据硬编码 | 从 report version/block source 加载 | backend/platform/reports/postgresql_store.py | test_report_integrity.py; PostgreSQL integration |
| F16 | 加载最新数据按序号给旧值加增量 | 创建新快照并记录 source partition | backend/platform/ingestion/postgresql_store.py immutable partition/latest artifact | test_data_acquisition.py |
| F17 | 重新生成结论是固定模板 | 基于选定证据包异步生成和评审 | backend/platform/api/routes/analysis.py; backend/platform/orchestration/workflow.py | test_semantic_execution_correctness.py |
| F18 | 周报版本缺少发布状态和不可变性 | draft→review→published→withdrawn、父版本和 checksum | backend/platform/reports/postgresql_store.py immutable version/checksum/status | test_report_integrity.py |
| F19 | GET 触发学习写入且多角色辩论为模板 | 异步学习候选，经人工审核后生效 | backend/platform/reports/weekly_learning.py; review candidates | test_weekly_learning.py; test_report_integrity.py |
| F20 | 评论整数组覆盖且作者不真实 | 单条 CRUD、真实作者、revision 和并发测试 | backend/platform/reports/postgresql_store.py; src/app/components/weekly-report/CommentsPanel.tsx | test_report_integrity.py; PostgreSQL integration |
| F21 | 图片 base64 重复存入报告 JSON | 对象存储 attachment_id、hash 和授权 URL | backend/platform/knowledge/files.py; backend/platform/api/routes/attachments.py | test_knowledge_lifecycle.py |
| F22 | 脚本、质量监控和系统参数仅展示 | 参数进入运行时，脚本真实执行，质量规则有结果 | backend/platform/ingestion/service.py; backend/platform/settings/postgresql_store.py | test_data_acquisition.py |
| G01 | ThreadingHTTPServer 无中间件和访问日志 | ASGI 类型化 API、鉴权、日志和异常中间件 | backend/platform/api/asgi.py; pyproject.toml smart-data-agent-asgi entrypoint | test_asgi_runtime.py |
| G02 | 浏览器超时与后端长任务不一致且无法取消 | 异步 job、deadline、cancel 和状态轮询/推送 | analysis async/cancel routes; backend/platform/automation/runtime.py | test_automation_runtime.py; test_asgi_runtime.py |
| G03 | 无队列、重试、outbox、死信、租约和恢复 | 持久 Job 状态机和 transactional outbox | backend/platform/automation/postgresql_store.py; backend/platform/automation/runtime.py | test_automation_runtime.py; PostgreSQL integration |
| G04 | Health 永远 ok，指标不是单调计数 | liveness/readiness/provider health 与标准 metrics | backend/platform/api/server.py::_runtime_health; backend/platform/api/support.py metrics | test_asgi_runtime.py; test_local_concurrency.py |
| G05 | Trace 无父子、耗时、token/cost 和查询 API | OpenTelemetry/Langfuse 兼容 span 与 artifact 关联 | backend/platform/observability/trace.py; trace API route | test_trace_telemetry.py |
| G06 | 失败分析无任务，Review 失败仍 completed | queued/running/review_required/succeeded/failed/cancelled | backend/platform/orchestration/state.py; workflow final review gate | test_automation_runtime.py; test_semantic_execution_correctness.py |
| G07 | 路由清单不是 OpenAPI | DTO 自动 OpenAPI 和前端 client generation | backend/platform/api/router.py OpenAPI 3.1 contract; scripts/generate_api_client.py; src/app/services/generatedApiClient.ts | route/OpenAPI tests; generated-client drift gate |
| G08 | 无 Python 依赖清单且路径依赖 cwd | pyproject/lock、可安装包和资源路径校验 | pyproject.toml; requirements.lock; resource paths resolved from __file__ | locked CI install; wheel build; full unittest discovery |
| G09 | 无 CI、容器、生产启动和滚动升级 | dev/staging/prod 完整交付流水线 | .github/workflows/ci.yml; Dockerfile; scripts/provision_production.py | CI release gates; production runtime tests |
| G10 | 启动异常被吞并形成部分成功 | 关键依赖失败拒绝 readiness，非关键明确 degraded | backend/platform/api/server.py readiness; backend/platform/runtime_config.py | test_asgi_runtime.py; test_runtime_config.py |
| G11 | 三个核心前端文件超过 3000 行 | 不改视觉，抽 domain hooks、client、状态机和 schema | domain modules under src/app/components/*; scripts/check_frontend_module_size.py | tsc; Vite build; 3000-line CI gate |
| G12 | 测试未证明数值、SQL、图表和周报一致 | golden dataset、provenance、reconciliation 测试 | semantic/report golden and reconciliation suites | test_semantic_execution_correctness.py; test_report_integrity.py |
| G13 | 缺少 E2E、并发、负载、迁移、恢复和安全测试 | 全部成为发布门禁 | CI gates; backend/platform/tests/test_postgresql_stores_integration.py | 206 tests; real PG; 100-read burst; frontend smoke; schema drift; npm/pip audit |

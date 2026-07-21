# Smart Data Agent 平台架构优化说明

## 1. 本次优化结论

上一版项目主要是前端页面原型和权限模块。本次优化先完成平台后端第一阶段骨架，把项目从页面 demo 调整为可持续演进的 Semantic Data Agent Platform。

核心变化：

- 新增 `backend/platform`，区分语义问数、Skill、MCP、Agent 编排、知识库、记忆库、图谱、模型、观测和数据加工。
- 新增 `configs`，把 Agent、Skill、MCP Server、Prompt 配置外置。
- 新增 `configs/agent_groups`，把工程开发、算法工程师两个 Agent 组的总控、专业 Agent、评审门禁和协作规则配置化。
- 新增 `SkillConfigCatalog`，校验 Agent 引用的所有 Skill 都在平台能力清单中注册。
- 新增 `backend/platform/schema.sql`，把平台治理数据表和权限表分离。
- 保留 `backend/authz`，通过 `PermissionBroker` 接入平台能力层。
- 新增测试，验证权限、Skill、SuperSonic 适配、知识召回、记忆写入、Trace 和 MCP 脱敏链路可运行。

## 2. 和 Supersonic 架构的对应关系

Supersonic 的核心价值是 Chat BI 与 Headless BI 统一：自然语言查询不能直接让 LLM 写 SQL，而要经过语义模型和语义层治理。

本项目中的对应落点：

| Supersonic 能力 | 本项目落点 | 说明 |
|---|---|---|
| Knowledge Base | `backend/platform/knowledge` | 存指标口径、业务规则、历史报告、SQL 样例和制度文件 |
| Schema Mapper | `backend/platform/semantic` | 由 SuperSonic 适配层承接，不在 Agent 内直接实现 |
| Semantic Parser | `backend/platform/semantic` | 统一封装到 `SemanticQueryService` |
| Semantic Corrector | `backend/platform/semantic` | 查询前后做语义合法性和 SQL 合规校验 |
| Semantic Translator | `backend/platform/semantic` | 语义查询转 SQL，由 SuperSonic 内核负责 |
| SQL Executor | `supersonic.query` Skill | Agent 只调用 Skill，不直接执行 SQL |
| Chat Plugin | `backend/platform/skills` + `backend/platform/mcp` | 外部能力统一包装成 Skill |
| Chat Memory | `backend/platform/memory` | 历史查询轨迹和分析案例沉淀为记忆 |
| Dataset/Column/Row ACL | `backend/authz` + `PermissionBroker` | 权限前置到 Skill 和数据访问前 |

## 3. 和原架构文件的对应关系

| 原架构层 | 本项目落点 |
|---|---|
| Application Layer | `src/app` |
| Intent & Context Router | `backend/platform/orchestration/workflow.py` 当前先内置路由，后续独立为 router |
| Agent Orchestration Layer | `backend/platform/orchestration` |
| Skill & MCP Capability Layer | `backend/platform/skills`、`backend/platform/mcp` |
| SuperSonic Semantic Query Core | `backend/platform/semantic` |
| Knowledge, Memory & Graph Layer | `backend/platform/knowledge`、`backend/platform/memory`、`backend/platform/graph` |
| Data Processing & Analysis Layer | `backend/platform/data_processing` |
| LLM Gateway & Model Layer | `backend/platform/llm` |
| Governance, Observability & Eval | `backend/authz`、`backend/platform/governance`、`backend/platform/observability` |

## 4. 当前代码结构

```text
backend/
  authz/                      # RBAC/ABAC 权限引擎
  platform/
    api/router.py             # API 统一接口目录和对外契约清单
    api/routes/               # API 适配边界
    agents/                   # Agent 元数据
    governance/               # PermissionBroker
    data_access/              # JSON mock 仓 / DB-API 数据库与数仓适配边界
    semantic/                 # SuperSonic 适配层
    skills/                   # Skill Registry / Executor
    mcp/                      # MCP Gateway
    orchestration/            # Agent 编排状态机
    knowledge/                # 知识库
    memory/                   # 记忆库
    reports/                  # 周报分析结果、评论快照和报表协作状态
    graph/                    # 图谱模型
    llm/                      # 模型与 Prompt Registry
    observability/            # Trace
    data_processing/          # Python 沙箱边界
    bootstrap.py              # 本地平台服务装配
    schema.sql                # 平台表结构

configs/
  agents/
  agent_groups/
  skills/
  mcp_servers/
  prompts/
```

## 5. Agent 组与能力配置

本轮已把两个附件中的 Agent 组结构落入配置：

```text
configs/agent_groups/engineering.json
configs/agent_groups/algorithm.json
```

工程开发组包含：工程开发总控、需求分析、任务规划、技术架构、数据库架构、后端开发、前端开发、安全权限、MCP工具工程、工作流工程、集成联调、测试、工程评审、完成度检查。

算法工程师组包含：算法工程师总控、建模目标解析、数据集设计、算法数据质量、特征工程、模型选择、训练验证、评估指标、模型解释、模型服务、MLOps、监控漂移、反馈闭环、算法风控合规、算法评审、算法报告 Writer。

平台侧读取入口：

```text
backend/platform/agents/catalog.py
backend/platform/skills/catalog.py
```

验收规则：

- Agent 组必须有总控 Agent。
- 工程组必须有安全权限、MCP 工具工程、完成度检查。
- 算法组必须有算法风控合规、监控漂移、算法评审。
- Agent 引用的所有 Skill 必须能在 `configs/skills` 中找到。

## 6. 已落地的请求链路

当前最小链路：

```text
run_analysis API adapter
-> ExecutionContext
-> AnalysisWorkflow
-> PlannerAgent 路由
-> KnowledgeAgent 检索知识
-> SkillExecutor
-> PermissionBroker
-> supersonic.query Skill
-> SemanticQueryService
-> PermissionBroker.metric_access（指标、字段、行过滤）
-> SupersonicClient boundary（支持远程 HTTP SuperSonic，失败时本地 JSON mock 语义仓显式降级）
-> DataQueryAgent 记录结果
-> VisualizationAgent 生成受控 Python 脚本并通过 PythonSandbox 产出可视化 artifact
-> InsightAgent 生成摘要
-> ReviewAgent 做数据、SQL、指标映射、图表一致性检查
-> MemoryStore 写入 analysis_case
-> TraceRecorder 记录 span
-> RuntimeEvent 记录成功/失败、耗时、fallback 状态
-> AnalysisTaskRepository 持久化任务和 trace
```

这条链路保留本地可运行能力，同时新增 SQLite 策略仓储、知识库、记忆库、分析任务仓储和运行事件仓储，并通过 `backend/platform/api/server.py` 暴露 `/api/analysis/run`。`SelfAnalysis` 页面通过前端服务适配层调用该接口，接口不可用时只展示明确错误和空状态，不再静默渲染本地伪分析结果；本地无数据库、无数仓、无外部系统时，后端通过 `data/mock/semantic_datasets.json` 和 `backend/platform/data_access/JSONDataWarehouse` 提供租户安全的 JSON mock 仓，保证系统链路畅通。数据访问层同时提供 `SQLDataWarehouse`，用 DB-API 连接工厂接 SQLite、PostgreSQL 或企业数仓驱动，数据集、表、指标、维度来自目录白名单，租户和筛选条件始终参数化传入；`build_data_warehouse_from_env()` 默认装配 JSON mock，设置 `SMART_DATA_AGENT_DATA_WAREHOUSE=sqlite`、`SMART_DATA_AGENT_SQLITE_WAREHOUSE_PATH` 和 `SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG` 后，完整语义查询链路会切换到 SQLite/DB-API 仓库，并在 `/api/health` 的 `data_source_mode` 中暴露当前模式。语义查询返回数据后，`AnalysisWorkflow` 会生成受控 Python 可视化脚本，交给 `backend/platform/data_processing/PythonSandbox` 执行并返回 `visualization_artifact`；该本地实现只允许 `build_chart(data, context)` 声明式函数，后续接真实 Python Worker 或容器沙箱时保持输出契约不变。自助分析保存和周报引用已迁入 `backend/platform/reports`：`/api/reports/analysis-results`、`/api/reports/analysis-result` 保存可视化结果快照，`/api/reports/comments` 保存周报评论和追评快照，前端仍保留原有周报页面结构、评论气泡和下划线交互。左侧机构下拉的显示名称会通过 `tenantIdFromInstitution()` 转为 `tenant:机构名称`，作为分析请求的租户上下文进入后端 `ExecutionContext`、权限校验、语义查询参数、任务持久化和记忆沉淀。本地平台种子已为附件中的运营机构生成管理员/操作员角色，并保留 `tenant_demo` 兼容路径。权限种子现在按幂等方式写入 SQLite，平台启动不再清空权限表，避免后续角色、授权和策略配置在重启后丢失。用户管理已从前端静态数组迁出第一步：`backend/platform/access` 管理用户目录和用户-角色授权，`/api/access/users` 与 `/api/access/user` 支持按当前机构查询、保存、删除用户，保存后会写入 `auth_role_assignments` 并立即影响菜单、指标和系统配置权限判断；角色权限页也已接入 `backend/platform/access`，`/api/access/role-policies` 和 `/api/access/role-policy` 会把机构权限配置转换为真实 `auth_permission_policies` 和 `auth_manageable_roles`。MCP 已从单纯网关推进到配置化 mock 接入：`configs/mcp_servers` 定义 database/knowledge Server，`backend/platform/mcp/registry.py` 将 database MCP 绑定到 JSON mock 数仓，将 knowledge MCP 绑定到知识库，并通过 `/api/mcp/servers`、`/api/mcp/tools`、`/api/mcp/call` 暴露受权限治理和脱敏保护的统一调用入口。API 请求用户和租户上下文统一收敛到 `APIRequestContext` 和 `backend/platform/security`：开发模式继续支持 `X-User-Id`、`X-Tenant-Id` Header 以保证本地页面可跑，其中中文租户 ID 会在前端编码并由后端解码；`SMART_DATA_AGENT_AUTH_MODE=strict` 时受保护接口必须使用签名 Bearer token，后端会忽略 body/query 中伪造的 `user_id`、`tenant_id`。左侧导航也已从纯前端硬编码推进到后端权限驱动：`backend/platform/navigation.py` 基于 `MENU_TREE` 和 `PermissionBroker` 生成 `/api/navigation` 的可见菜单树，`Layout` 保留现有路径、图标和页面结构，只按后端返回的 `menu_keys` 过滤菜单；如果后端不可用，页面保留本地菜单降级。指标字典已从纯前端 localStorage 迁出第一步：`backend/platform/metrics` 提供租户化指标字典仓储，`/api/metric-dictionary` 支持按机构查询、整批初始化、单条保存和删除，`DataAssets` 页面在结构不变的前提下优先使用后端并保留本地降级。系统配置页的模型接入和数据接入也已迁出纯前端状态：`backend/platform/settings` 提供租户化仓储，`/api/system-config` 支持查询，`/api/system-config/model` 和 `/api/system-config/data-connection` 支持保存和删除；数据接入保存前会进入 `backend/platform/security/secrets.py` 的本地密钥编码边界，保存后只向前端返回密码掩码，不回传明文；`/api/system-config/data-connection/test` 会基于当前 `DataWarehouse` 配置匹配数据集目录并执行样例查询，让数据接入从“保存账号密码”推进到“可验证可调用”。审计日志已从前端静态示例推进到后端事件流：`backend/platform/audit` 提供内存和 SQLite 仓储，用户授权、角色权限、模型接入、数据接入、指标字典等关键写操作都会写入 `platform_audit_events`，`/api/audit-logs` 按租户返回最近事件，系统管理审计日志页优先展示真实事件并保留接口不可用时的本地降级。语义层可通过 `SMART_DATA_AGENT_SUPERSONIC_URL` 接入远程 SuperSonic HTTP 服务，远程失败时自动回落到当前本地仓库，并在 `semantic_info.fallback`、`fallback_reason` 中显式标记。健康检查会返回最近请求的成功、错误、fallback、耗时、统一接口数量和 `data_source_mode` 摘要，`/api/metrics` 提供 Prometheus 风格指标，`/api/routes` 提供机器可读接口目录。`DataAssets` 的质量监控二级页面已通过 `src/app/services/systemHealthApi.ts` 接入 `/api/health`，在不改变页面导航结构的前提下展示服务状态、语义层模式、数据源模式、运行样本、错误/降级和平均耗时。后续替换为 PostgreSQL、向量库或 Langfuse 时，不应改前端页面和业务流程，只替换接口实现。

## 7. 下一步建议

第一优先级：

- 把 `TraceRecorder` 替换为 Langfuse Adapter。
- 把 `/api/metrics` 接入 Prometheus，后续再补 OpenTelemetry trace exporter。
- 把 SQLite Knowledge/Memory Store 升级为 PostgreSQL + 向量库。
- 在 `SQLDataWarehouse` 之外补 PostgreSQL、Hive、Doris 等生产驱动的连接池、方言和只读查询审计适配器。
- 把角色权限弹窗里的菜单、数据范围、可管理角色配置继续迁入后端 role-policy API。
- 把前端重型图表依赖继续做 vendor chunk 拆分和按需加载。

第二优先级：

- 把 `AnalysisWorkflow._route` 拆成独立 Intent Router。
- 增加 `trend.analysis`、`chart.generate`、`report.generate` 的真实 Skill。
- MCP Gateway 接真实数据库、文件、知识库、企业系统 MCP Server。
- 增加 Review Agent 对 SQL、指标口径、权限、结论一致性的规则检查。

第三优先级：

- 建知识图谱：指标、维度、数据集、表、字段、产品、渠道、客户、风险事件。
- 建评测体系：SQL 正确性、RAG 引用准确性、Agent 计划质量、结论可信度、成本和延迟。
- 建多租户数据持久化和机构级隔离部署策略。

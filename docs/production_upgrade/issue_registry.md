# 114 项生产化整改台账

更新时间：2026-07-10。总数固定为 114；不得通过合并、隐藏或删除条目减少问题数。证据列中的文件或测试将在整改过程中持续补充。

## A. 总体架构、Agent、Skill、MCP（10 项）

| 编号 | 级别 | 问题摘要 | 状态 | 目标验收 |
|---|---|---|---|---|
| A01 | P0 | 三条执行路径没有统一事实源 | 已完成 | 所有计划、查询、产物、结论和评审归属同一 execution_id |
| A02 | P1 | 30 个 Agent 仅为配置目录 | 已完成 | AgentSpec 能被真实加载、执行、授权和追踪 |
| A03 | P1 | Agent Group 门禁未进入运行流程 | 已完成 | stage/review gate 编译为可恢复状态机 |
| A04 | P1 | 41 个 Skill 仅 1 个有运行 handler | 已完成 | Skill 明确 configured/implemented/healthy/disabled 状态 |
| A05 | P0 | Skill 风险、权限、超时、重试和版本未执行 | 已完成 | Executor 强制 schema、权限、超时、重试、配额和审批 |
| A06 | P1 | MCP endpoint 无真实 transport，数据库 MCP 固定 Mock | 已完成 | 标准 MCP transport 使用当前授权 Warehouse |
| A07 | P0 | MCP allowed_agents 被忽略，未知工具返回 mocked | 已完成 | 用户、Agent、工具、数据域全校验且未知工具 fail closed |
| A08 | P1 | 模型、Prompt 与系统配置割裂 | 已完成 | 统一模型注册、密钥、路由、Prompt 版本和调用审计 |
| A09 | P1 | 图谱只有数据类，没有真实血缘 | 已完成 | 指标到字段、数据集、报告和结论可双向追踪 |
| A10 | P1 | Agent/Skill/MCP/Evaluation 声明与运行库分叉 | 已完成 | Schema catalog、迁移和逐表文档来自同一事实源 |

## B. 分析正确性与数据真实性（20 项）

| 编号 | 级别 | 问题摘要 | 状态 | 目标验收 |
|---|---|---|---|---|
| B01 | P0 | 展示 SQL 与实际执行 SQL 不一致 | 已完成 | 新执行 0 不一致，历史记录有迁移/标记，SQL hash 一致 |
| B02 | P0 | Workflow 与 IntelligentAnalysisEngine 是两条链 | 已完成 | plan→compile→execute→visualize→conclude→review 单链路 |
| B03 | P0 | 页面 Python 与真实执行脚本不一致 | 已完成 | 执行脚本与 hash 可追溯，候选脚本显式标记未执行 |
| B04 | P0 | Review 发生在最终结果形成之前 | 已完成 | Review 对最终证据包执行，失败不能标成功 |
| B05 | P0 | 前端按行号编造经营指标 | 已完成 | 缺失字段只显示不可用，源代码和浏览器均无推导逻辑 |
| B06 | P0 | 多指标计划只执行第一个指标 | 已完成 | 同粒度多指标或多查询主键合并均有正确性测试 |
| B07 | P0 | 多维计划只执行第一个维度 | 已完成 | 多维聚合、下钻和粒度校验真实生效 |
| B08 | P0 | 时间、TopN、排序过滤未解析 | 已完成 | 类型化条件进入执行计划、参数和 SQL |
| B09 | P0 | 率指标错误使用 AVG 和 SUM | 已完成 | 指标版本保存分子分母和 aggregation semantics |
| B10 | P0 | 前 20 行被误称总体合计 | 已完成 | 独立总计查询与分页明细，结论只引用完整汇总 |
| B11 | P0 | LLM 不接收真实查询证据 | 已完成 | Prompt 仅引用裁剪脱敏的已执行结果和 evidence_id |
| B12 | P0 | 可能结论为固定模板 | 已完成 | 每条结论引用指标、维度、值、时间和快照 |
| B13 | P0 | Demo key/真实模型失败仍可能成功 | 已完成 | mock/real/degraded/failed 状态不可混淆 |
| B14 | P0 | 人工修改计划、SQL、Python 后重跑被忽略 | 已完成 | 指定 revision 被真实编译执行并产生新 execution |
| B15 | P0 | 未验证主题表 SQL 被称为 Verified | 已完成 | 语法、权限、租户条件、列和样例结果全部校验 |
| B16 | P0 | SQL 标识符拼接缺少 catalog 校验 | 已完成 | 只允许已授权元数据标识符，禁止任意前端标识符 |
| B17 | P0 | 指标字典未进入语义计划和 SQL | 已完成 | 可执行 semantic model 解析公式、单位、粒度和来源 |
| B18 | P0 | 行列权限在查询后过滤 | 已完成 | tenant/row/field/metric ACL 下推到数据源 |
| B19 | P0 | 空集合、缺字段、图表字段存在 ACL 绕过 | 已完成 | 缺少权限字段直接拒绝，空集合返回零行 |
| B20 | P0 | 缺少新鲜度、分区、快照、版本和事实一致性 | 已完成 | immutable Evidence Bundle 成为报告发布门禁 |

## C. 数据接入、数据资产、知识和记忆（14 项）

| 编号 | 级别 | 问题摘要 | 状态 | 目标验收 |
|---|---|---|---|---|
| C01 | P0 | 所有租户默认读取相同 JSON Mock | 已完成 | Demo 环境隔离，生产和发布流程拒绝 Mock |
| C02 | P0 | 页面保存的数据连接未进入分析运行时 | 已完成 | 执行按授权 connection_id/version 创建连接 |
| C03 | P0 | 连接测试忽略用户填写的连接信息 | 已完成 | 按 source type 真实认证、catalog 和 sample query |
| C04 | P0 | 启用连接即标 connected | 已完成 | draft→testing→verified→degraded/disabled 状态机 |
| C05 | P1 | SQL Warehouse 只支持环境 SQLite 和单一方言 | 已完成 | PostgreSQL、Doris/Hive、QBI/API、CSV/对象存储适配器 |
| C06 | P1 | 缺少数据获取脚本、实时/离线流和修复流程 | 已完成 | Script Version、Job、Run、Artifact、Failure、Repair Proposal 闭环 |
| C07 | P1 | 缺少元数据、CSV 索引和 latest artifact 查询 | 已完成 | 支持 getLatestCsvByTopicTable(topic_table_id, org_id) 等稳定接口 |
| C08 | P0 | 读路径混入代码默认数据 | 已完成 | 初始化显式 seed，查询只返回持久化事实 |
| C09 | P0 | 数据资产缺少严格 schema、引用和审批 | 已完成 | 每类资产有 schema、FK、版本和审批状态 |
| C10 | P1 | 三套知识/附件系统互不相通 | 已完成 | 统一 Document/Version/Chunk/Attachment/Citation |
| C11 | P0 | 上传文件未真实保存、解析或索引 | 已完成 | 对象存储、病毒扫描、OCR、分块、索引和状态 |
| C12 | P0 | 文件正文重复进入 action/audit/task | 已完成 | 审计仅存 ID/hash/分类，不复制正文 |
| C13 | P0 | 子串检索弱且 doc_id 可跨租户覆盖 | 已完成 | tenant UUID、所有权、混合检索、重排和引用 |
| C14 | P1 | 记忆只写不读且无生命周期 | 已完成 | Candidate→Review→Active→Superseded/Expired，并进入规划 |

数据接入实施范围明确包含：市场公开/商业数据源，以及毓数/智能运营系统的 API、数据库、文件或批量交换接入；每类来源都必须有独立 source identity、认证版本、同步游标、数据分区、新鲜度和质量证据。

## D. 数据库设计与一致性（15 项）

| 编号 | 级别 | 问题摘要 | 状态 | 目标验收 |
|---|---|---|---|---|
| D01 | P0 | 声明 schema 与真实运行表不一致 | 已完成 | 迁移和 schema catalog 成为唯一结构事实源 |
| D02 | P0 | user_version=0 且无迁移历史 | 已完成 | 空库/旧库迁移、幂等和 checksum 漂移测试通过 |
| D03 | P1 | Store 启动时自行 CREATE/ALTER | 已完成 | Store 无 DDL，结构只由迁移创建 |
| D04 | P0 | 核心表缺少租户、用户和业务外键 | 已完成 | 逐表 FK、删除策略和跨租户约束完整 |
| D05 | P1 | 核心业务对象大量整块 JSON | 已完成 | 可查询字段规范化，仅扩展属性使用 JSONB |
| D06 | P1 | 独立列与 JSON payload 双写漂移 | 已完成 | 单一主字段来源或数据库一致性约束 |
| D07 | P0 | 状态、范围和 JSON 缺少 CHECK | 已完成 | 枚举、范围、JSON 类型和业务约束入库 |
| D08 | P0 | 整块覆盖导致并发丢更新 | 已完成 | 行级实体、PATCH、lock_version/ETag |
| D09 | P0 | 写接口无幂等键 | 已完成 | 生成、发送、触发、保存均支持幂等去重 |
| D10 | P1 | 时间字段格式混乱 | 已完成 | 数据库统一 timestamptz UTC，展示层本地化 |
| D11 | P1 | 机构是静态字符串而非主数据 | 已完成 | Tenant/OrgUnit 稳定 ID、层级、编码和生效状态 |
| D12 | P0 | ID、作者、状态和时间可由客户端伪造 | 已完成 | 服务端生成并验证状态迁移 |
| D13 | P1 | 单进程打开大量独立 SQLite 连接 | 已完成 | 本地连接管理；生产 PostgreSQL pool |
| D14 | P1 | SQLite/WAL 不适合多实例并发 | 已完成 | 生产 PostgreSQL，开发库有 checkpoint/backup/vacuum |
| D15 | P1 | 无归档、保留、PITR、软删和分页索引 | 已完成 | 生命周期、PITR、append-only audit 和索引基线 |

## E. 身份、租户、权限与安全（20 项）

| 编号 | 级别 | 问题摘要 | 状态 | 目标验收 |
|---|---|---|---|---|
| E01 | P0 | 已知邮箱即可登录 | 已完成 | OIDC/SAML/企业 IdP 或至少密码/OTP |
| E02 | P0 | strict 模式仍允许邮箱登录 | 已完成 | strict 仅接受可信身份源且禁匿名注册 |
| E03 | P0 | 注册可自选机构并获得角色 | 已完成 | 邀请、员工校验或管理员审批 |
| E04 | P0 | development 身份头默认可信 | 已完成 | 仅 loopback 显式开启，生产默认 strict |
| E05 | P0 | 重启重新插入默认角色和授权 | 已完成 | 撤销角色/权限、删除账号后重启均不恢复 |
| E06 | P0 | 超级管理员身份硬编码且前端可升级会话 | 已完成 | 权限仅以后端 claims 为准 |
| E07 | P0 | Token 存 localStorage | 已完成 | HttpOnly/Secure/SameSite 会话 Cookie |
| E08 | P1 | Token 无标准会话、撤销和轮换 | 已完成 | issuer/audience/jti/kid、refresh、revocation、device session |
| E09 | P1 | 页面会话策略不进入认证运行时 | 已完成 | idle/absolute/refresh timeout 真正生效 |
| E10 | P0 | CORS=* 且本机身份头可被网页调用 | 已完成 | Origin/Host allowlist 和身份头禁用 |
| E11 | P0 | WebSocket query token 泄露风险 | 已完成 | Cookie 或一次性短期 ticket |
| E12 | P0 | 无登录、分析、模型、MCP、上传限流 | 已完成 | user/tenant/IP/provider 多维限流和预算 |
| E13 | P0 | 无 TLS、安全头、WS Origin/大小/时长限制 | 已完成 | 网关/ASGI 强制 TLS 和资源限制 |
| E14 | P0 | 用户 URL 测试存在 SSRF | 已完成 | allowlist、DNS/IP 校验和受控 egress |
| E15 | P1 | 自制密钥封装且有默认开发 key | 已完成 | KMS/Vault envelope encryption 与 key version |
| E16 | P0 | Action/Audit 保存完整敏感 payload | 已完成 | 字段级审计、脱敏、摘要 hash 和数据分类 |
| E17 | P1 | str(exc) 直接返回客户端 | 已完成 | 稳定错误码/request_id，详情仅内部日志 |
| E18 | P0 | 页面数据范围未落实行列指标权限 | 已完成 | org/metric/field/row scope 编译并下推 |
| E19 | P0 | Todo/Task 缺少所有者对象级授权 | 已完成 | owner/assignee ACL 覆盖查改删 |
| E20 | P0 | 菜单隐藏不等于路由授权，报告无个人范围 | 已完成 | 路由 guard 与 owner/shared scope |

## F. 页面功能真实完成度（22 项）

| 编号 | 级别 | 页面/能力问题 | 状态 | 目标验收 |
|---|---|---|---|---|
| F01 | P1 | 管理驾驶舱静态指标 | 已完成 | 接统一查询服务和指标快照 |
| F02 | P1 | 业务漏斗静态数组 | 已完成 | 漏斗定义、事实表和转化口径 |
| F03 | P0 | 经营沙盘使用固定常数公式 | 已完成 | 模型版本、校准数据、范围、置信区间 |
| F04 | P1 | 客群分析静态数据 | 已完成 | 画像主题表和分群版本 |
| F05 | P1 | 竞品分析无来源证据 | 已完成 | 市场来源、采集时间、证据和对比口径 |
| F06 | P1 | 机构督导静态数组 | 已完成 | 组织、目标、实绩、问题和督导任务 |
| F07 | P0 | 邮件日报仅改 sent 状态 | 已完成 | 正文、队列、provider id、送达和失败回执 |
| F08 | P0 | 推送与订阅为静态数组 | 已完成 | 规则、订阅、事件和真实 Delivery Adapter |
| F09 | P0 | 自动化任务没有调度与 Worker | 已完成 | trigger/run/lease/retry/checkpoint/cancel |
| F10 | P1 | 任务运行状态可由客户端填写 | 已完成 | 仅 Worker 状态机可推进 |
| F11 | P1 | 加载 Skill 只增加名称 | 已完成 | 安装、签名、版本、依赖、健康和执行 |
| F12 | P0 | 导出只返回文件名或基于伪数据 CSV | 已完成 | 真实 artifact、hash、下载授权和过期时间 |
| F13 | P0 | 未识别通用动作也返回成功 | 已完成 | 未注册动作 4xx，注册动作有 handler 和结果 |
| F14 | P0 | 右下角 Agent 失败时返回硬编码数字 | 已完成 | 真实状态、证据和明确失败/降级 |
| F15 | P0 | 周报初始数据硬编码 | 已完成 | 从 report version/block source 加载 |
| F16 | P0 | 加载最新数据按序号给旧值加增量 | 已完成 | 创建新快照并记录 source partition |
| F17 | P0 | 重新生成结论是固定模板 | 已完成 | 基于选定证据包异步生成和评审 |
| F18 | P1 | 周报版本缺少发布状态和不可变性 | 已完成 | draft→review→published→withdrawn、父版本和 checksum |
| F19 | P0 | GET 触发学习写入且多角色辩论为模板 | 已完成 | 异步学习候选，经人工审核后生效 |
| F20 | P0 | 评论整数组覆盖且作者不真实 | 已完成 | 单条 CRUD、真实作者、revision 和并发测试 |
| F21 | P0 | 图片 base64 重复存入报告 JSON | 已完成 | 对象存储 attachment_id、hash 和授权 URL |
| F22 | P1 | 脚本、质量监控和系统参数仅展示 | 已完成 | 参数进入运行时，脚本真实执行，质量规则有结果 |

## G. API、并发、可观测性、测试和部署（13 项）

| 编号 | 级别 | 问题摘要 | 状态 | 目标验收 |
|---|---|---|---|---|
| G01 | P1 | ThreadingHTTPServer 无中间件和访问日志 | 已完成 | ASGI 类型化 API、鉴权、日志和异常中间件 |
| G02 | P0 | 浏览器超时与后端长任务不一致且无法取消 | 已完成 | 异步 job、deadline、cancel 和状态轮询/推送 |
| G03 | P1 | 无队列、重试、outbox、死信、租约和恢复 | 已完成 | 持久 Job 状态机和 transactional outbox |
| G04 | P1 | Health 永远 ok，指标不是单调计数 | 已完成 | liveness/readiness/provider health 与标准 metrics |
| G05 | P1 | Trace 无父子、耗时、token/cost 和查询 API | 已完成 | OpenTelemetry/Langfuse 兼容 span 与 artifact 关联 |
| G06 | P1 | 失败分析无任务，Review 失败仍 completed | 已完成 | queued/running/review_required/succeeded/failed/cancelled |
| G07 | P1 | 路由清单不是 OpenAPI | 已完成 | DTO 自动 OpenAPI 和前端 client generation |
| G08 | P1 | 无 Python 依赖清单且路径依赖 cwd | 已完成 | pyproject/lock、可安装包和资源路径校验 |
| G09 | P1 | 无 CI、容器、生产启动和滚动升级 | 已完成 | dev/staging/prod 完整交付流水线 |
| G10 | P1 | 启动异常被吞并形成部分成功 | 已完成 | 关键依赖失败拒绝 readiness，非关键明确 degraded |
| G11 | P2 | 三个核心前端文件超过 3000 行 | 已完成 | 不改视觉，抽 domain hooks、client、状态机和 schema |
| G12 | P1 | 测试未证明数值、SQL、图表和周报一致 | 已完成 | golden dataset、provenance、reconciliation 测试 |
| G13 | P1 | 缺少 E2E、并发、负载、迁移、恢复和安全测试 | 已完成 | 全部成为发布门禁 |

## 总体验收结果

- 114/114 项均已完成代码闭环并纳入 [逐项实现与自动化验收证据](./implementation_evidence.md)。
- PostgreSQL 生产主路径、99 张表、显式初始化、100 用户规模连接池突发、权限安全、迁移恢复和前后端发布门禁均已验证。
- 对尚未配置真实外部 provider、预测模型或数据集的能力，系统采用 fail closed / unavailable，不使用 Mock 或固定数字伪装成功。


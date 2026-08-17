# Smart Data Agent 数据库逐表设计

目标生产模型共 **106 张表**。表数量由业务边界和可追溯性决定，与用户数并非线性关系；约 100 人规模仍采用模块化单体和同一 MySQL 集群。

MySQL 8.x 是结构化数据运行主库；DDL 位于 `backend/platform/database/mysql/0001_production_schema.sql`。PostgreSQL DDL 仅保留为迁移源对照，SQLite 仅用于迁移测试。每张表均有独立 Markdown，且与 DDL 由同一 schema catalog 生成。

## 领域统计

| 领域 | 表数 |
|---|---:|
| Agent与模型 | 11 |
| 可观测性 | 2 |
| 基础设施 | 5 |
| 外部集成 | 2 |
| 市场监控 | 5 |
| 指标语义 | 6 |
| 数据接入 | 14 |
| 数据治理 | 7 |
| 智能分析 | 12 |
| 知识记忆 | 8 |
| 经营周报 | 9 |
| 自动化与通知 | 11 |
| 身份权限 | 12 |
| 页面兼容 | 2 |

## 逐表目录

### Agent与模型

- [`platform_agents`](./platform_agents.md)：可运行 Agent 定义和启用状态。
- [`platform_agent_groups`](./platform_agent_groups.md)：多 Agent 编排组及阶段门禁定义。
- [`platform_agent_group_members`](./platform_agent_group_members.md)：Agent 在编排组中的顺序、职责和门禁。
- [`platform_skills`](./platform_skills.md)：Skill 配置、实现、版本和运行策略。
- [`platform_agent_skill_grants`](./platform_agent_skill_grants.md)：Agent 被允许使用的 Skill 及版本范围。
- [`platform_mcp_servers`](./platform_mcp_servers.md)：MCP Server 注册、认证和健康状态。
- [`platform_mcp_tools`](./platform_mcp_tools.md)：从 MCP Server 同步并授权的工具目录。
- [`platform_model_integrations`](./platform_model_integrations.md)：大模型提供商、模型路由和加密凭证版本。
- [`platform_speech_integrations`](./platform_speech_integrations.md)：ASR/TTS 提供商接入和凭证。
- [`platform_prompt_templates`](./platform_prompt_templates.md)：版本化 Prompt 模板及发布状态。
- [`platform_model_calls`](./platform_model_calls.md)：模型调用的输入证据引用、用量、成本和结果状态。

### 可观测性

- [`platform_trace_spans`](./platform_trace_spans.md)：OpenTelemetry 兼容的父子 Span、耗时和资源属性。
- [`platform_runtime_events`](./platform_runtime_events.md)：系统运行事件、状态和降级记录。

### 基础设施

- [`platform_schema_migrations`](./platform_schema_migrations.md)：记录已执行数据库迁移及不可变校验和。
- [`platform_idempotency_keys`](./platform_idempotency_keys.md)：写请求幂等、重复提交和结果重放。
- [`platform_audit_events`](./platform_audit_events.md)：脱敏、追加写的安全与业务审计事件。
- [`platform_outbox_events`](./platform_outbox_events.md)：事务内登记待发布领域事件，支持可靠异步副作用。
- [`platform_system_data_params`](./platform_system_data_params.md)：可审计且真正进入运行时的租户系统参数。

### 外部集成

- [`platform_bridge_bindings`](./platform_bridge_bindings.md)：WorkBuddy、Codex、QWork 一次点击授权形成的可撤销 Bridge 设备绑定；只保存令牌哈希。
- [`platform_bridge_enrollments`](./platform_bridge_enrollments.md)：十分钟内有效、只能领取一次的 Bridge 设备授权事务。

### 市场监控

- [`platform_market_sources`](./platform_market_sources.md)：市场数据来源、许可、抓取方式和可信度。
- [`platform_market_entities`](./platform_market_entities.md)：竞品、机构、产品、行业等市场实体主数据。
- [`platform_market_observations`](./platform_market_observations.md)：带来源、时间、单位和证据的市场指标观测值。
- [`platform_market_monitoring_rules`](./platform_market_monitoring_rules.md)：对市场实体和指标的阈值、变化和事件监控规则。
- [`platform_market_monitoring_events`](./platform_market_monitoring_events.md)：市场规则命中事件、证据和处置状态。

### 指标语义

- [`platform_metric_dictionary`](./platform_metric_dictionary.md)：指标逻辑身份和当前发布版本。
- [`platform_metric_versions`](./platform_metric_versions.md)：不可变指标口径、公式、分子分母、粒度和来源版本。
- [`platform_metric_visibility`](./platform_metric_visibility.md)：按用户、角色或组织授予指标可见范围。
- [`platform_topic_tables`](./platform_topic_tables.md)：主题表逻辑身份、发布版本和新鲜度要求。
- [`platform_topic_table_fields`](./platform_topic_table_fields.md)：主题表输出字段及其来源映射。
- [`platform_topic_table_sources`](./platform_topic_table_sources.md)：主题表依赖的数据集及连接版本。

### 数据接入

- [`platform_data_connections`](./platform_data_connections.md)：租户数据连接的逻辑身份和当前验证版本。
- [`platform_connection_versions`](./platform_connection_versions.md)：不可变数据连接配置与加密凭证版本。
- [`platform_datasets`](./platform_datasets.md)：真实数据集、库表、API 资源或文件集合的元数据。
- [`platform_dataset_fields`](./platform_dataset_fields.md)：数据集字段、类型、语义、权限和敏感分类。
- [`platform_acquisition_scripts`](./platform_acquisition_scripts.md)：数据获取脚本逻辑身份和已发布版本。
- [`platform_acquisition_script_versions`](./platform_acquisition_script_versions.md)：不可变获取脚本版本、签名和审批结果。
- [`platform_acquisition_jobs`](./platform_acquisition_jobs.md)：实时/离线/API/文件数据获取任务定义。
- [`platform_acquisition_job_runs`](./platform_acquisition_job_runs.md)：每次数据获取执行、租约、游标、错误和产物。
- [`platform_acquisition_repair_proposals`](./platform_acquisition_repair_proposals.md)：采集失败后的受控诊断与脚本修复候选，必须评审后才能形成新版本。
- [`platform_data_artifacts`](./platform_data_artifacts.md)：CSV/Parquet/JSON/图表/导出等不可变对象存储产物。
- [`platform_dataset_partitions`](./platform_dataset_partitions.md)：数据集分区、快照、新鲜度和对应 Artifact。
- [`platform_file_attachments`](./platform_file_attachments.md)：业务对象与对象存储文件之间的授权引用。
- [`platform_source_systems`](./platform_source_systems.md)：外部来源系统主数据，包括市场平台和毓数/智能运营系统。
- [`platform_operating_system_mappings`](./platform_operating_system_mappings.md)：毓数/智能运营系统与平台机构、客户、指标、主题表编码映射。

### 数据治理

- [`platform_data_quality_rules`](./platform_data_quality_rules.md)：数据完整性、准确性、一致性和新鲜度规则。
- [`platform_data_quality_results`](./platform_data_quality_results.md)：质量规则对指定分区/快照的执行结果。
- [`platform_lineage_edges`](./platform_lineage_edges.md)：字段、指标、主题表、分析、报告之间的有向血缘。
- [`platform_data_asset_items`](./platform_data_asset_items.md)：兼容现有数据资产页面的版本化目录记录。
- [`platform_raw_table_external_references`](./platform_raw_table_external_references.md)：CSV 原始表在 SDA 中的外部引用授权；不写入或修改 CSV 文件。
- [`platform_data_asset_versions`](./platform_data_asset_versions.md)：数据资产不可变版本、schema 校验结果与发布状态。
- [`platform_data_asset_reviews`](./platform_data_asset_reviews.md)：数据资产版本的追加式人工复核决策。

### 智能分析

- [`platform_analysis_tasks`](./platform_analysis_tasks.md)：一次分析请求的聚合根和权威状态。
- [`platform_analysis_steps`](./platform_analysis_steps.md)：分析计划中每个 Agent/Skill/Review 步骤的可恢复执行记录。
- [`platform_analysis_queries`](./platform_analysis_queries.md)：经权限编译并真实执行的 SQL/语义查询和结果摘要。
- [`platform_analysis_artifacts`](./platform_analysis_artifacts.md)：脚本、图表、表格、草稿和结论等分析产物。
- [`platform_analysis_evidence`](./platform_analysis_evidence.md)：结论与查询、分区、数据值、知识引用之间的证据边。
- [`platform_evaluations`](./platform_evaluations.md)：对最终 SQL、数据、图表、结论和权限的质量评审。
- [`platform_saved_analysis_results`](./platform_saved_analysis_results.md)：用户收藏的分析执行引用，不复制任务事实。
- [`platform_analysis_feedback`](./platform_analysis_feedback.md)：用户对分析结果的评分、纠错和采用结果。
- [`platform_analysis_workspaces`](./platform_analysis_workspaces.md)：页面、报告或自主分析对应的持久化分析工作区。
- [`platform_analysis_threads`](./platform_analysis_threads.md)：总体分析及图表、指标、机构或数据点的分支线程。
- [`platform_analysis_turns`](./platform_analysis_turns.md)：线程内不可变问题、回答、规划和证据轮次。
- [`platform_analysis_result_cache`](./platform_analysis_result_cache.md)：权限、CSV、语义和执行版本绑定的安全结果缓存索引。

### 知识记忆

- [`platform_knowledge_documents`](./platform_knowledge_documents.md)：租户隔离的知识文档逻辑身份和处理状态。
- [`platform_knowledge_versions`](./platform_knowledge_versions.md)：不可变知识正文版本及对象存储来源。
- [`platform_knowledge_chunks`](./platform_knowledge_chunks.md)：知识版本的可检索分块、关键词与向量引用。
- [`platform_knowledge_citations`](./platform_knowledge_citations.md)：分析结论、报告块对知识分块的可验证引用。
- [`platform_memory_records`](./platform_memory_records.md)：分析案例、用户习惯、业务经验等记忆候选和正式记录。
- [`platform_memory_evidence`](./platform_memory_evidence.md)：记忆记录的分析、报告、任务或知识证据。
- [`platform_memory_reviews`](./platform_memory_reviews.md)：记忆候选的人工或受控机器评审记录。
- [`platform_analysis_experiences`](./platform_analysis_experiences.md)：可审核、可版本化、可在规划阶段召回的分析经验。

### 经营周报

- [`platform_reports`](./platform_reports.md)：报告逻辑身份、所有者、模板和当前版本。
- [`platform_weekly_report_versions`](./platform_weekly_report_versions.md)：不可变周报版本、发布状态、父版本和校验和。
- [`platform_report_blocks`](./platform_report_blocks.md)：报告版本中的表格、图表、文本、结论和图片块。
- [`platform_report_block_sources`](./platform_report_block_sources.md)：报告块与分析、查询、数据分区和知识证据之间的来源关系。
- [`platform_report_comments`](./platform_report_comments.md)：报告版本或块上的单条评论和解决状态。
- [`platform_report_comment_replies`](./platform_report_comment_replies.md)：评论线程中的单条回复。
- [`platform_report_comment_revisions`](./platform_report_comment_revisions.md)：逻辑报告评论集合的单调修订号与快照校验和。
- [`platform_report_learning_candidates`](./platform_report_learning_candidates.md)：从周报版本提炼的经验、习惯和待办候选。
- [`weekly_report_ai_analysis_task`](./weekly_report_ai_analysis_task.md)：兼容现有周报 AI 分析任务并关联正式报告/分析事实链。

### 自动化与通知

- [`platform_automation_tasks`](./platform_automation_tasks.md)：定时、事件和手动自动化任务定义。
- [`platform_automation_task_runs`](./platform_automation_task_runs.md)：自动化任务每次运行、租约、重试和恢复状态。
- [`platform_job_steps`](./platform_job_steps.md)：自动化运行中的步骤、检查点和补偿状态。
- [`platform_todos`](./platform_todos.md)：可分配、提醒、关联证据和回收结果的待办任务。
- [`platform_alert_rules`](./platform_alert_rules.md)：数据、任务、指标和系统异常的统一告警规则。
- [`platform_alert_events`](./platform_alert_events.md)：告警规则命中、去重、确认、解决和证据。
- [`platform_subscriptions`](./platform_subscriptions.md)：用户对报告、指标、告警和市场事件的推送订阅。
- [`platform_notification_deliveries`](./platform_notification_deliveries.md)：每条通知的真实渠道投递、回执和重试。
- [`platform_daily_report_runs`](./platform_daily_report_runs.md)：从可发布报告证据生成的不可变日报邮件产物及投递汇总。
- [`platform_email_messages`](./platform_email_messages.md)：邮件主题、正文产物、收件人和发送回执。
- [`platform_provider_callbacks`](./platform_provider_callbacks.md)：邮件、飞书、企微等渠道回调的幂等原始事件摘要。

### 身份权限

- [`platform_tenants`](./platform_tenants.md)：租户/机构隔离根实体。
- [`platform_org_units`](./platform_org_units.md)：租户内组织机构树和数据权限范围。
- [`platform_user_profiles`](./platform_user_profiles.md)：平台用户身份档案，不在此表保存密码。
- [`platform_user_tenant_memberships`](./platform_user_tenant_memberships.md)：用户与租户/组织的成员关系。
- [`platform_user_sessions`](./platform_user_sessions.md)：可撤销的用户设备会话和刷新令牌摘要。
- [`platform_oidc_transactions`](./platform_oidc_transactions.md)：OIDC Authorization Code + PKCE 登录的一次性事务。
- [`auth_roles`](./auth_roles.md)：全局或租户级角色定义。
- [`auth_role_assignments`](./auth_role_assignments.md)：用户在指定租户内的角色授权。
- [`auth_permission_policies`](./auth_permission_policies.md)：角色的资源、动作、组织、行列和指标权限策略。
- [`auth_manageable_roles`](./auth_manageable_roles.md)：定义某角色允许管理的下级角色。
- [`platform_capability_approvals`](./platform_capability_approvals.md)：高风险 Skill 与 MCP 调用的一次性限时审批票据。
- [`platform_user_preferences`](./platform_user_preferences.md)：用户在租户内的非安全偏好设置。

### 页面兼容

- [`platform_application_module_state`](./platform_application_module_state.md)：现有页面非核心 UI 状态的服务端持久化兼容层。
- [`platform_application_actions`](./platform_application_actions.md)：已注册页面动作的命令记录和真实 handler 结果。

## 生成与漂移检查

```bash
python3 scripts/generate_database_schema.py --check
python3 scripts/generate_database_schema.py --write
```

`--check` 用于 CI，任何手工修改生成文件或漏生成逐表文档都会失败。

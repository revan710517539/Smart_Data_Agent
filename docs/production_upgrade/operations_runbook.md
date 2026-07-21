# Smart Data Agent 生产运行手册

## 运行拓扑（约 100 用户）

- API：ASGI/Uvicorn，多实例无状态部署；健康端点为 `/api/live`、`/api/ready`。
- Worker：与 API 使用独立进程和数据库连接池；自动化任务依赖租约、重试、取消和 outbox。
- 主库：PostgreSQL，高可用主备；生产 DDL 由 `scripts/generate_database_schema.py` 生成，使用 `scripts/migrate_postgresql.py` 在 advisory lock 下应用。
- 分布式状态：Redis 仅用于限流等可重建状态，不作为业务事实源。
- 文件：启用版本化和服务端加密的 S3/OSS；数据库只保存对象引用、内容 hash 和扫描状态。
- 分析仓：PostgreSQL、Doris、Hive、QBI/智能运营 HTTP 或不可变 CSV/object adapter；Mock 不能进入发布链路。

## 发布门禁

1. `npm run typecheck`、`npm run build`、全部 Python 单元/集成测试、前端权限 smoke 和 schema drift 检查全部通过。
2. 生产配置必须通过 `validate_runtime_config()`；strict OIDC、显式 CORS、Redis、KMS、对象存储、ClamAV、egress allowlist 缺一项都拒绝启动。
3. 在 staging 对 PostgreSQL 迁移做一次空库创建和一次幂等重跑；校验 99 张表和迁移 checksum。
4. readiness 必须确认主库、Redis、对象存储和 Worker；真实分析必须确认数据源快照、指标版本、权限下推和 evidence bundle。
5. 采用滚动发布；先扩 schema、再发布兼容代码、最后收缩旧字段。禁止在同一次发布中先删除旧列。

## 首次部署与显式初始化

生产环境不会隐式创建租户、管理员、角色或演示数据。首次部署按下面顺序执行，命令重复运行必须保持幂等：

```bash
python3 scripts/migrate_postgresql.py --database-url "$SMART_DATA_AGENT_DATABASE_URL"
python3 scripts/provision_production.py \
  --database-url "$SMART_DATA_AGENT_DATABASE_URL" \
  --tenant-code tenant:bank \
  --tenant-name "示例银行" \
  --super-admin-subject oidc:admin@example.com \
  --super-admin-email admin@example.com \
  --users-file /run/secrets/smart-data-agent-users.json \
  --skip-schema
smart-data-agent-asgi --host 0.0.0.0 --port 8000 --workers 2
```

`users-file` 是 JSON 数组；每项至少包含 `subject`、`email`、`display_name`，可选 `role`、`department_code` 和 `department_name`。身份 subject 必须与企业 IdP 的稳定 subject 一致，不得使用邮箱猜测或前端传入角色。

生产启动至少需要：`SMART_DATA_AGENT_ENV=production`、strict OIDC 全套地址、32 字节以上认证密钥、带 `sslmode=require` 或更强约束的 PostgreSQL URL、`rediss://`、KMS 命令、S3/OSS bucket/region、ClamAV、HTTPS CORS origin 和受控 egress allowlist。缺项时进程应拒绝 readiness，不允许回落到开发身份、SQLite、Mock 数据仓或本地明文密钥。

## PostgreSQL 备份与 PITR

- RPO：不高于 5 分钟；RTO：不高于 60 分钟。
- 开启 WAL archive，并将 base backup、WAL 和校验清单写入独立账号/区域的加密存储。
- 每日 base backup，WAL 连续归档；保留周期不低于 35 天。审计归档周期按合规要求单独配置。
- 每月进行一次隔离环境恢复演练：恢复到随机时间点，执行 schema checksum、租户隔离抽查、分析 evidence hash 和对象引用完整性检查。
- 恢复演练证据必须记录恢复点、耗时、缺失 WAL、表计数、抽样 hash 和负责人；演练失败阻断下一次生产发布。

## SQLite 本地维护

SQLite 仅用于本地开发/单进程演示。可运行：

```bash
python3 scripts/sqlite_maintenance.py check --db .smart_data_agent.sqlite
python3 scripts/sqlite_maintenance.py backup --db .smart_data_agent.sqlite --backup-dir backups
python3 scripts/sqlite_maintenance.py vacuum --db .smart_data_agent.sqlite
```

备份使用 SQLite online backup API，并对备份执行 `integrity_check` 后原子落盘。不得把该流程当作生产多实例数据库方案。

## 故障处置

- 主库不可用：readiness 立即失败，停止接收新写入；不得回落到 SQLite 或内存。
- 分析仓不可用：任务进入 failed/degraded；禁止用 Mock 结果替换并标成功。
- 对象存储或病毒扫描不可用：上传保持 pending/failed，不得创建可检索知识或可发布报告。
- 模型不可用：记录稳定错误码和 hash/usage 审计；固定模板只能标记 degraded，不能伪装为真实模型结果。
- 通知 provider 失败：delivery 按退避重试，超过阈值进入死信；回调按 provider event ID 幂等。

## 容量基线

- API 应用连接池建议每实例 8–12，Worker 每实例 4–8；总连接数必须小于 PostgreSQL 连接预算的 70%。
- 单用户智能分析并发默认 2；单租户/用户/IP/provider 均有限流。
- SQL statement timeout 默认 30 秒；分析总体 deadline 默认 900 秒；异步执行支持取消。
- 上传、OCR、HTTP 响应、CSV 对象、查询行数和图表点数均有硬限制，不能依赖前端限制。

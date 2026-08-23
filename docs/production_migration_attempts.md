# 生产迁移尝试审计

`platform_schema_migration_attempts` 是生产 MySQL 的 append-only migration 尝试审计表。
每次迁移记录 `running`、`succeeded` 或 `failed` 状态、语句总数、最后语句位置、耗时、
脱敏错误摘要和运行镜像 Git SHA。

该表由 additive migration `0035_migration_attempts.sql` 创建，只用于发布诊断和审计，
不参与业务查询，也不属于 `0001_production_schema.sql` 的生成式基线表目录。失败记录
不得通过删除或修改 checksum 掩盖；后续修复必须新增更高版本 migration。

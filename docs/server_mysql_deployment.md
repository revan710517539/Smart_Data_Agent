# Smart Data Agent 生产服务器部署契约

## 不变边界

- 目标主库是 MySQL 8.0.18；禁止修改 migration ledger checksum。
- Data Crawler 宿主机目录固定为
  `/opt/palywright/examples/data-crawler/runtime-data`，在 SDA 内只读挂载为
  `/app/data`；容器内 `SMART_DATA_AGENT_DATA_CRAWLER_ROOT=/app/data`。SDA 不修改
  Crawler 源码、容器和源数据。
- 原始数据不进入镜像；`/app/runtime` 与 `/app/Topic_Data` 使用 SDA 独立持久卷。
- 生产仅接受严格 OIDC、Redis TLS、KMS、S3/OSS、ClamAV 和显式 egress allowlist。
- 任何 Skill/Memory 候选仍需人工审批；部署本身不等于激活。

## 版本与配置

1. 从干净工作树的完整 40 位 Git SHA 构建镜像：

   ```bash
   ./scripts/build-image.sh <40位SHA>
   ```

2. 将 `.env.production.example` 复制为受保护的 `.env.production`，只在部署平台
   Secret 区填真实值。不得把数据库、OIDC、模型、对象存储或 KMS 凭据写入 Git、
   日志和聊天。
3. `SMART_DATA_AGENT_IMAGE` 必须是精确 SHA tag；Dockerfile 的 OCI revision label
   必须与 tag、待发布 Commit 一致。

## 发布前门禁

CI 或生产等价候选必须提供 MySQL 8.0.18，并运行：

```bash
./scripts/release-gate.sh
./scripts/check-mysql-closure.sh
docker compose --env-file .env.production -f docker-compose.server.yml config --quiet
```

门禁核验源码、wheel/site-packages、镜像 SQL 闭包，前端预压缩资源、组件尺寸、
完整后端测试和真实浏览器本地认证合同。已发布 migration 只能追加，
`configs/deployment/mysql-migration-checksums.json` 必须与仓库 SQL 一致。

## 候选拓扑与启动顺序

生产 Compose 只使用同一精确 SHA 镜像，按以下顺序启动：

```text
migration（一次性、成功后退出）
  └─ capabilities（一次性；准备基础 Skill 与待审机构 Skill/Memory）
       └─ worker（独立进程，写共享心跳）
            └─ api（ASGI；读取 Worker 心跳进入 readiness）
```

API 和 Worker 均固定 `SMART_DATA_AGENT_AUTO_MIGRATE=false`。migration job 使用
命名锁、checksum 和 append-only ledger；失败时 API/Worker 不启动。

```bash
docker compose --env-file .env.production -f docker-compose.server.yml up migration
```

首次空库在 migration 成功后、API 切流前，按已批准机构显式运行：

```bash
docker compose --env-file .env.production -f docker-compose.server.yml run --rm migration \
  python /app/scripts/provision_production.py --skip-schema \
  --tenant-slug "<机构规范名称>" --tenant-name "<机构显示名>" \
  --super-admin-subject u_super_admin \
  --super-admin-email "<已批准邮箱>" --super-admin-name "<已批准姓名>"
```

本项目现有 11 家机构能力包以既有 canonical ID（例如 `tenant:华兴银行`）为
外键，首次生产建租户必须与 `configs/analysis/institution_analysis_profiles.json`
逐项一致；不得由前端或显示名称临时推导另一个 ID。登录、恢复、refresh 和切机构
均使用后端 `tenant_directory`。

所有租户建好后再运行能力准备并启动长期进程：

```bash
docker compose --env-file .env.production -f docker-compose.server.yml up capabilities
docker compose --env-file .env.production -f docker-compose.server.yml up -d worker api
SMART_DATA_AGENT_EXPECTED_SHA=<40位SHA> \
  ./scripts/candidate-smoke.sh http://127.0.0.1:8787
```

`build-image.sh` 会在 `artifacts/releases/<40位SHA>/` 生成脱敏
`release-receipt.json` 和 `SHA256SUMS`，记录镜像 ID/digest、OCI revision、SBOM、MySQL
目标版本与关键交付文件校验和。候选门禁会回读 `/api/ready` 的完整 SHA、MySQL 8.0.18
及首页实际引用的全部 JS/CSS，并分别记录页面和静态资源耗时。

`capabilities` 只激活 7 条平台基础场景/方法 Skill；33 条机构覆盖 Skill 保持
`review`，110 条机构 Memory 保持 `candidate`，不会绕过四眼审批。API 与 Worker
启动时只验证这组能力，不再并发写入。

## Data Crawler 合同

挂载根目录必须包含 `manifest.json`，schema 为
`smart-data-crawler-manifest/v1`。每个租户条目必须包含 canonical `tenant_id`、
`institution_directory`、租户 schema 版本、文件相对路径和 SHA-256、生成时间。

```bash
docker compose --env-file .env.production -f docker-compose.server.yml exec api \
  ./scripts/data-crawler-contract-smoke.sh
```

生产不再按中文名称猜目录。`/api/data-assets` 的 `source.csv_source` 会返回
`contract_status`、`contract_error`、tenant、目录、manifest/schema 版本和生成时间，
并区分 manifest 缺失、映射缺失、schema 不兼容、文件缺失/checksum 不符和无文件。

## 认证与模型链验收

用已完成候选 OIDC 登录的专用 Chrome profile 运行：

```bash
SMART_DATA_AGENT_AUTH_E2E_URL=https://candidate.example \
SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE=/protected/sda-candidate-profile \
./scripts/auth-e2e.sh
```

该门禁在真实浏览器中验证 `/api/auth/me` canonical tenant 目录、cookie-only 与
canonical header 导航、代表性 `/api/data-assets`、切机构、单次 refresh、刷新后
业务请求，并拒绝任何 401/429 风暴。

模型在“模型接入”中保存后先为 draft/untested；真实连接测试成功并启用至少一个
provider 返回的子模型后才进入分析运行时。测试失败或未测试的模型不会被智能分析、
周报重生成、自动分析、Memory/Skill 运行时选择。API Key 只以加密密文保存，HTTP
读取仅返回掩码。完整页面、场景、Skill 调度和表达契约见
`docs/production_model_skill_runtime.md`。

## 切换、证据与回滚

切换前保存：脱敏 `docker inspect`、镜像 ID/Commit、migration ledger、数据库备份/
恢复点、runtime/topic 卷备份、Crawler mount 盘点、公网 readiness、SHA256SUMS 和
浏览器验收结果。旧容器停止但保留，作为代码回滚单元。

回滚只切回上一精确 SHA 镜像和 Compose；不要清空数据库、删除 ledger、更新
checksum 或改 Crawler 数据。若新 migration 已执行，数据库回退只使用上线前已验证
恢复点，并与容器回滚分别留痕、审批和验收。

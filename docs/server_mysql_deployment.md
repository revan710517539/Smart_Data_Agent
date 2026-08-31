# Smart Data Agent 生产服务器部署契约

## 不变边界

- 目标主库是 MySQL 8.0.18；禁止修改 migration ledger checksum。
- Data Crawler 与 SDA 必须设置完全相同的 `DATA_CRAWLER_MOUNT_TYPE` 和
  `DATA_CRAWLER_MOUNT_SOURCE`。`bind` 使用规范化宿主机绝对目录，`volume` 使用现有
  Docker 卷名。Data Crawler 将该 Source 读写挂载到 `/app/data`，SDA 将同一 Source
  只读挂载到 `/app/data`；容器内始终使用
  `SMART_DATA_AGENT_DATA_CRAWLER_ROOT=/app/data`。严格 Compose 的
  `DATA_CRAWLER_SHARED_VOLUME` 必须等于 volume Source。不得用个人 checkout、另一
  宿主目录、复制 CSV 或只比较容器内路径来冒充同一数据源。SDA 不修改 Crawler
  源码、容器和源数据。
- 原始数据不进入镜像；`/app/runtime` 与 `/app/Topic_Data` 使用 SDA 独立持久卷。
- 生产仅接受严格 OIDC、Redis TLS、KMS、S3/OSS、ClamAV 和显式 egress allowlist。
- 任何 Skill/Memory 候选仍需人工审批；部署本身不等于激活。
- 发布必须显式设置 `SMART_DATA_AGENT_TARGET_PLATFORM` 为 `linux/amd64` 或
  `linux/arm64`，并与候选、生产宿主机的实际架构一致。不得让 Apple Silicon
  开发机的默认架构隐式决定服务器镜像；候选和生产架构不一致时切流前失败关闭。

## 服务器部署档位

### 当前 CentOS 7 Development 档位

当前服务器是直接 Docker + systemd，没有 Compose。SDA 保持 development auth、local
object store 和 embedded worker；不要求额外安装 OIDC、Redis、S3、ClamAV、KMS 或
独立 Worker。Crawler bind Source 的实值只写在受保护配置和部署回执中，路径变化时
同时更新两项目的 `DATA_CRAWLER_MOUNT_SOURCE`；业务代码和容器内 `/app/data` 不变。

准备受保护环境文件后，先验证挂载、镜像和配置，再验证备份/恢复回执并运行一次迁移：

```bash
export SMART_DATA_AGENT_SERVER_ENV_FILE=/protected/sda/development.env
export SMART_DATA_AGENT_IMAGE=sha256:<不可变本地ImageID或repository@digest>
export SMART_DATA_AGENT_COMMIT_SHA=<40位SHA>
export SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64
export SMART_DATA_AGENT_CONTAINER_NAME=smart-data-agent-candidate-<40位SHA>
export SMART_DATA_AGENT_HTTP_BIND=127.0.0.1
export SMART_DATA_AGENT_HTTP_PORT=18787
export DATA_CRAWLER_MOUNT_TYPE=bind
export DATA_CRAWLER_MOUNT_SOURCE=/protected/data-crawler/runtime-data
export SMART_DATA_AGENT_RUNTIME_MOUNT_TYPE=volume
export SMART_DATA_AGENT_RUNTIME_MOUNT_SOURCE=smart-data-agent-runtime-candidate
export SMART_DATA_AGENT_TOPIC_DATA_MOUNT_TYPE=volume
export SMART_DATA_AGENT_TOPIC_DATA_MOUNT_SOURCE=smart-data-agent-topic-candidate
export SMART_DATA_AGENT_DB_BACKUP_RECEIPT=/protected/backups/receipt.json
export SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS=86400
export SMART_DATA_AGENT_MIGRATION_RECEIPT_DIR=/protected/release-receipts
./scripts/server-development-container.sh validate
./scripts/server-development-container.sh preflight
./scripts/server-development-container.sh migrate
./scripts/server-development-container.sh create-candidate
```

受保护 env 中的 `SMART_DATA_AGENT_MYSQL_TLS_MODE` 必须与数据库 URL 的 `ssl_mode`
一致。当前 Development 服务器已确认是 `required`，因此不要求 CA 文件；仅当目标环境
实际提供 CA 且模式为 `verify_ca`/`verify_identity` 时，才额外导出
`SMART_DATA_AGENT_MYSQL_CA_HOST_PATH=/protected/mysql/ca.pem`。`required` 只证明加密
传输，不得描述成 CA/主机身份验证。

备份回执不包含 DSN 或凭据，格式固定为：

```json
{
  "schema_version": "smart-data-agent-mysql-backup-receipt/v1",
  "created_at": "<带时区的ISO-8601时间>",
  "source": {
    "mysql_version": "8.0.18",
    "database_fingerprint_sha256": "<64位小写SHA-256>"
  },
  "backup": {
    "file": "<相对回执目录的备份文件名>",
    "sha256": "<64位小写SHA-256>",
    "bytes": 1
  },
  "restore_test": {
    "status": "passed",
    "verified_at": "<不早于created_at的带时区时间>",
    "target": "isolated"
  }
}
```

`bytes` 必须替换为真实非零大小。回执文件、大小、Hash、MySQL 版本、隔离恢复顺序和
最大年龄全部通过后才允许 migration；历史回执不能复用到新发布。

Migration 成功回执由目标镜像内 `migrate_mysql.py` 生成，并由
`mysql_migration_receipt.py` 在落盘前和候选创建前各验证一次；它绑定完整 40 位 commit、
MySQL 8.0.18、0001 基线 Hash、当前最新 additive migration 和 migration manifest
Hash。仅修改文件名或复制旧回执不能给新 revision 放行。

`create-candidate` 只创建精确命名的停止容器，不启动、不替换旧容器、不切流。安装
`configs/deployment/smart-data-agent-docker-mss.service` 时，必须先备份并原子替换现网
同名 unit，禁止并行安装第二个 SDA controller；
`/etc/sysconfig/smart-data-agent` 只保存精确容器名；systemd 不依赖项目 checkout 路径。
Development 直连拓扑由 systemd 单独负责启动和异常重启，候选容器固定
`--restart no`，不得再同时启用 Docker `unless-stopped` 形成双重主管。unit 不硬编码
MySQL service 名；数据库连通和 TLS 身份由 preflight/migration 门禁验证。
Crawler 数据卷继续使用 `volume-nocopy` 防止镜像占位内容进入权威数据源；SDA 自身的
runtime/Topic 新卷则保留 Docker 首次挂载 copy-up，以继承镜像内 `app:app` 权限，随后
仍由 preflight 实测两个目录可写。
Crawler 对同一 bind Source 必须通过其 `verify_shared_volume_mount.py` 回读为 RW，SDA
候选和生产必须回读为 RO。不得递归 `chmod`、创建第二目录或复制 460 份 CSV。

### 严格 Production Compose 档位

当 OIDC、Redis TLS、KMS、外部对象存储、ClamAV 和独立 Worker 均已实际提供时，使用
部署平台内受保护的 `.env.production` 与 `docker-compose.server.yml`。环境文件不进入
Git；所需变量以 Compose 中的必填 `${VAR:?说明}` 契约为准。Compose 不是当前服务器的
必装依赖，也不得因为服务器缺少这些可选组件而改写 Development 业务行为。

## 版本与配置

1. 从干净工作树的完整 40 位 Git SHA 进入统一门禁；`build-image.sh` 只由门禁调用：

   ```bash
   SMART_DATA_AGENT_RELEASE_SCOPE=build \
   SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64 \
   ./scripts/release-gate.sh <40位SHA>
   ```

2. 直接在部署平台 Secret 区创建受保护的 `.env.production`，按
   `docker-compose.server.yml` 的必填变量契约填写真实值。不得把数据库、OIDC、
   模型、对象存储或 KMS 凭据写入 Git、日志和聊天。
3. `SMART_DATA_AGENT_IMAGE` 必须是 registry 返回的
   `repository@sha256:<64位摘要>`；SHA tag 只可作为构建期定位，不能作为部署身份。
   Dockerfile 的 OCI revision label、源码闭包摘要和待发布 Commit 必须一致。

## 发布前门禁

CI 或生产等价候选必须提供 MySQL 8.0.18，并运行：

```bash
SMART_DATA_AGENT_RELEASE_SCOPE=candidate \
SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64 \
SMART_DATA_AGENT_TOOLCHAIN_IMAGE=registry.example.com/sda-release-toolchain@sha256:<64位工具链镜像摘要> \
SMART_DATA_AGENT_CANDIDATE_URL=https://candidate.example \
SMART_DATA_AGENT_CANDIDATE_CONTAINER=<候选容器名或ID> \
DATA_CRAWLER_MOUNT_TYPE=bind \
DATA_CRAWLER_MOUNT_SOURCE=/protected/data-crawler/runtime-data \
SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE=/protected/sda-candidate-profile \
SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID='tenant:华兴银行' \
SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH='20260807_180009_员工维度报表.csv' \
SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH='<当前目录返回的完整64位SHA-256>' \
SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION='按二级部门分析当日在贷余额' \
./scripts/release-gate.sh <40位SHA>
```

门禁核验源码、wheel/site-packages、镜像 SQL 闭包，前端预压缩资源、组件尺寸、
完整后端测试、Crawler 同一只读卷、真实浏览器认证合同和指定 CSV 分析终态。门禁会把命令、工具链镜像 ID、环境版本、每步
起止时间和结果写入 `release-gate-report.json`；失败或中断不能生成通过回执。已发布 migration 只能追加，
`configs/deployment/mysql-migration-checksums.json` 必须与仓库 SQL 一致。

## 候选拓扑与启动顺序

生产 Compose 只使用候选验收过的同一镜像 digest，按以下顺序启动：

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

统一门禁会在 `artifacts/releases/<40位SHA>/` 生成脱敏
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

切流前的候选门禁不访问生产地址。完成备份并取得切流审批后，先在发布控制机执行：

```bash
SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID=sha256:<门禁记录的工具链镜像ID> \
SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64 \
SMART_DATA_AGENT_PRODUCTION_URL=https://sda.example.com \
SMART_DATA_AGENT_CURRENT_PRODUCTION_CONTAINER=<当前生产容器名或ID> \
./scripts/capture-pre-cutover.sh <40位SHA>
```

该只读命令必须在切流前完成；它把旧容器和旧 Image ID 写入脱敏回滚回执。随后完成
审批和切流，再执行：

```bash
SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID=sha256:<门禁记录的工具链镜像ID> \
SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64 \
SMART_DATA_AGENT_PRODUCTION_URL=https://sda.example.com \
SMART_DATA_AGENT_PRODUCTION_CONTAINER=<切流后的生产容器名或ID> \
DATA_CRAWLER_MOUNT_TYPE=bind \
DATA_CRAWLER_MOUNT_SOURCE=/protected/data-crawler/runtime-data \
SMART_DATA_AGENT_PRODUCTION_AUTH_E2E_CHROME_PROFILE=/protected/sda-production-profile \
SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID='tenant:华兴银行' \
SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH='20260807_180009_员工维度报表.csv' \
SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH='<当前目录返回的完整64位SHA-256>' \
SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION='按二级部门分析当日在贷余额' \
./scripts/verify-production-release.sh <40位SHA>
```

该命令比较候选和生产的完整 revision、镜像 digest、Docker Image ID、源码归档、依赖锁、前端资产、
工具链摘要，并分别记录容器 ID 与运行实例 ID；同时重新验证公网 readiness、OIDC 会话和受保护
接口。任一项不同都失败关闭，不能用 health 200 替代。

回滚只切回上一精确 SHA 镜像和 Compose；不要清空数据库、删除 ledger、更新
checksum 或改 Crawler 数据。若新 migration 已执行，数据库回退只使用上线前已验证
恢复点，并与容器回滚分别留痕、审批和验收。

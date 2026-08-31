# Smart Data Agent 生产开发与发布规范

- Standard ID: `sda-production-development/v1`
- Version: `1.1.0`
- Owner: Smart Data Agent 项目负责人
- Authority: 本文件是本仓库开发、测试、候选发布和生产交付的唯一项目级规范入口。

本规范吸收服务器侧《Smart Data Agent 生产开发与部署规范》的全部强制要求，并把
它们落到仓库门禁中。后续开发在设计、评审、实现、测试、构建和发布时必须引用
`sda-production-development/v1`。若本文件与更高优先级的安全、审批或基础设施规则
冲突，执行更严格的规则并记录差异；不得通过删除门禁、提高阈值或临时修改生产数据
规避要求。

## 1. 项目边界与非目标

Smart Data Agent 是独立的数据分析系统，不是 Data Crawler，也不是 Custom Insight
Simulator。SDA 只消费 Data Crawler 已落盘的数据，不修改 Crawler 源码、容器或源
数据。

```text
服务器权威存储：DATA_CRAWLER_MOUNT_TYPE + DATA_CRAWLER_MOUNT_SOURCE
Data Crawler 容器：同一 Source -> /app/data（读写）
SDA 容器：同一 Source -> /app/data（只读）
```

`DATA_CRAWLER_MOUNT_TYPE` 只允许 `bind` 或 `volume`；`DATA_CRAWLER_MOUNT_SOURCE`
分别是规范化的宿主机绝对目录或 Docker 卷名。必须比较 Docker mount 的实际 Type、
Source、目标路径和读写位，不能因为两个容器内路径相同就判定为同一数据源。严格
Compose 拓扑继续用 `DATA_CRAWLER_SHARED_VOLUME`，但它必须与
`DATA_CRAWLER_MOUNT_TYPE=volume`、`DATA_CRAWLER_MOUNT_SOURCE` 完全一致；该旧变量只是
volume 兼容入口，不是唯一服务器形态。直接 Docker/systemd 服务器可以使用受保护
环境配置中的 bind Source，目录变化时只更新配置，不修改业务代码或复制 CSV。
本机测试仍只能使用临时目录。业务 CSV 不进入镜像；`/app/runtime` 和
`/app/Topic_Data` 是 SDA 自己的持久存储。部署适配不得改变分析场景、模型选择、
Skill/Memory 语义、报表口径或其他业务模块。

## 2. 每次开发必须遵守的流程

任何代码变更在实现前必须说明：

1. 用户/角色、入口、前置条件和成功、空、失败、无权限路径；
2. 权威数据、API、认证、租户、任务、持久化、审计和直接消费者；
3. 最小改动范围、非目标、兼容性、验证、风险和回滚；
4. 是否触及数据库迁移、生产配置、Crawler 合同、模型运行时或发布拓扑。

实现时优先复用现有模块和合同。测试必须使用真实 `APIRequestContext` 或合同兼容
Fixture；Handler 测试桩必须支持真实响应签名。权限、安全上下文或 API 签名变化时，
同步更新集成测试和直接消费者。

提交前必须执行：

```bash
SMART_DATA_AGENT_RELEASE_SCOPE=candidate \
SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64 \
./scripts/release-gate.sh <40位SHA>
```

CI、候选和生产证据是不同层次。HTTP 200、构建成功、本地监听或截图都不是部署和
生产可用证明。

## 3. P0 数据库与迁移规则

生产结构化主库固定为 MySQL 8.0.18。

1. migration append-only；已发布文件不可删除、改名或修改任一字节；
2. 修复只能新增更高且唯一的 migration ID；禁止更新 ledger checksum；
3. 每次迁移必须记录 ID、SHA-256、状态、耗时和失败诊断；
4. CI 必须在真实 MySQL 8.0.18 上执行空库、重复执行、checksum 和 store 集成测试；
5. 源码、构建上下文、wheel/site-packages、镜像和生产 ledger 必须形成 SQL 闭包；
6. schema bootstrap 必须是独立一次性 Job，API/Worker 禁止自动迁移；
7. 运行时或 checker 使用的 SQL、config、schema 文档必须进入正确交付包；
8. MySQL DDL 可能隐式提交；partial DDL 不得自动删除，只能在证明对象为空、未使用、
   已备份并获得审批后处理；
9. 生产连接必须启用 TLS；`verify_ca` 必须校验证书，`verify_identity` 还必须校验主机名；
10. migration 和 readiness 必须验证实际 MySQL 版本，生产不是 8.0.18 时失败关闭。

迁移尝试表及诊断边界见 [`docs/production_migration_attempts.md`](docs/production_migration_attempts.md)。

迁移基线检查：

```bash
SMART_DATA_AGENT_MIGRATION_BASE_REF=<发布基线SHA> \
  uv run --frozen python scripts/check_mysql_migration_history.py
./scripts/check-mysql-closure.sh
```

禁止在应用启动时临时改写 SQL、从旧镜像长期提取 overlay、删除 migration ledger、
使用 root 应用账号或在未审批情况下修改数据库权限。

## 4. P0 认证与租户规则

1. 后端 Session 和 `/api/tenants` 返回的 canonical tenant ID 是唯一权威；
2. 中文显示名称只用于 UI，不生成数据库或请求 tenant ID；
3. Cookie/Bearer、tenant header、user header 冲突必须返回稳定错误码，并带 request ID
   和 trace ID；
4. 登录、refresh、缓存恢复、切租户和 API header 使用同一规范化函数；
5. refresh 请求必须合并，单一根因不得产生 401/429 风暴；
6. 生产验收必须使用真实浏览器和真实 OIDC Session，不能只测登录接口。

认证候选闭环：

```text
登录提交 -> Set-Cookie -> /api/auth/me -> Cookie-only /api/navigation
-> canonical tenant header /api/navigation -> /api/data-assets
-> tenant switching -> refresh 一次 -> 刷新后业务请求
-> 页面跳转 -> 无 401 storm / 429
```

## 5. P0 Data Crawler 数据合同

生产挂载根目录必须提供 `smart-data-crawler-manifest/v1` 的 `manifest.json`，包含 tenant、
机构目录、tenant schema 版本、文件相对路径、SHA-256 和生成时间。

1. `/app/data` 始终只读；SDA 不生成、修复或删除 Crawler 文件；
2. tenant 到目录只使用 manifest，不使用中文猜测或首项/其他租户兜底；
3. `/api/data-assets` 返回来源、tenant、表名、内容/文件版本和错误原因；
4. 空数据区分无文件、无权限、manifest 缺失、schema 不兼容、映射失败、文件缺失和
   checksum 不符；
5. 候选必须从宿主机 Source、容器 mount、manifest、后端 catalog、受保护 API 到浏览器
   页面逐层验证。

## 6. P1 前后端、可维护性和性能

1. 核心组件持续执行尺寸门禁；禁止提高阈值代替无行为变化的职责拆分；
2. API 请求上下文使用真实类型；
3. 前端生产构建生成并验证 Brotli/Gzip 预压缩资源；
4. UI 和 API 区分 401、403、404、422、500，不把鉴权、权限、缺失、校验和服务错误
   混为一个提示；
5. 交互埋点等非关键路径 best-effort，但失败必须有独立错误码、日志、指标和测试；
6. 关键页面提供稳定 role、aria 或 test id；
7. 性能测试分别记录冷缓存、热缓存、静态资源、认证 API 和业务 API；
8. 无界列表必须分页、稳定排序和硬上限；长任务进入有界 worker。

## 7. 双服务器拓扑与安全配置

### 7.1 当前 Development 等价服务器

CentOS 7 服务器允许使用直接 Docker + systemd，不要求安装 Compose。该拓扑必须
显式保持 `SMART_DATA_AGENT_ENV=development`、development auth、local object store、
embedded worker，并通过 Git 外的受保护环境文件与
`scripts/server-development-container.sh` 管理。环境文件的绝对路径由
`SMART_DATA_AGENT_SERVER_ENV_FILE` 指定。简化拓扑不要求独立 Worker、Redis、
OIDC、S3、ClamAV 或 KMS，但仍必须保留：MySQL 8.0.18 + TLS、`AUTO_MIGRATE=false`、
备份/隔离恢复回执、一次性 migration、不可变 Image ID/digest、完整 SHA、同源 Crawler
挂载、候选业务验证和可执行回滚。Development 模式不得直接公开绑定 `0.0.0.0`；公网
HTTPS/WSS/ASR 若对外提供，必须另行验证代理、会话和能力 readiness。
现网 Development MySQL 连接已确认使用 `ssl_mode=required`；此档位显式记录该模式且
不伪装成 CA 身份校验。具备 CA 时才切换为 `verify_ca`/`verify_identity` 并只读挂载 CA。
直连容器固定使用 `--restart no`，由 systemd 的 `Restart=always` 单独接管；禁止
Docker restart policy 与 systemd 同时重启同一容器。systemd unit 不硬编码未确认的
MySQL unit 名，MySQL readiness 由容器 preflight 和 migration 收据验证；交付 unit
复用现网 `smart-data-agent-docker-mss.service` 名称，禁止另装第二个 SDA controller。

当前服务器的精确 Source 只能存在于受保护环境配置和运维回执中，不能写死在业务代码
或版本化文档。Data Crawler 对该 Source 读写，SDA 对同一个 Source 只读；不得递归
改权限、迁移或复制目录来满足门禁。

### 7.2 严格 Production Compose

生产使用同一精确 SHA 镜像，顺序固定为：

```text
migration -> capabilities -> worker healthy -> api ready
```

API 和 Worker 固定 `SMART_DATA_AGENT_AUTO_MIGRATE=false`。生产只接受严格 OIDC、Redis
TLS、KMS、S3/OSS、ClamAV 和显式 egress allowlist。Secret 只从受保护配置注入，不写入
Git、镜像、日志、文档或聊天。容器必须非 root、只读根文件系统、移除 Linux
capabilities，并仅开放必要回环端口。

## 8. 标准发布门禁

仓库必须保留并执行：

```bash
SMART_DATA_AGENT_RELEASE_SCOPE=candidate \
SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64 \
DATA_CRAWLER_MOUNT_TYPE=bind \
DATA_CRAWLER_MOUNT_SOURCE=/受保护的服务器数据目录 \
./scripts/release-gate.sh <40位SHA>
```

这是进入候选环境前唯一允许标记“门禁通过”的入口。开发规范、MySQL 闭包、镜像构建、
Crawler 只读探针、候选业务 smoke、真实认证和指定 CSV 分析终态都由该入口调用；不得把
内部脚本拆开选择性执行后拼成通过结论。`capture-pre-cutover.sh` 与
`verify-production-release.sh` 分别属于审批后的切流前取证和切流后验收，不替代候选门禁。

完整门禁至少包含：diff 检查、开发规范合同、后端测试、MySQL 8.0.18、历史 migration
不可变、SQL/package/image/ledger 闭包、TypeScript、Vite build、组件尺寸、API 客户端、
开源依赖许可证/SBOM、预压缩资源、真实浏览器认证和 Crawler 只读联动。许可证规则见
[`docs/open_source_dependency_policy.md`](docs/open_source_dependency_policy.md)，商业闭源、
企业版或 source-available 依赖失败关闭。

镜像必须使用完整 Git SHA tag，并输出 OCI revision、镜像 ID/digest、SBOM、关键文件
SHA256SUMS 和脱敏发布回执。不得使用 `latest`、短 SHA 或未记录来源的镜像发版。
`SMART_DATA_AGENT_TARGET_PLATFORM` 必须显式为 `linux/amd64` 或 `linux/arm64`；工具链、
应用镜像、候选容器和生产容器的实际平台必须逐层回读一致。候选与生产平台不一致时，
不得用相同标签或多架构索引掩盖差异，必须在切流前失败关闭。
门禁默认止于候选环境，不得在切流前把“生产验证”伪装成已通过；完成备份和同一镜像
digest 切流后，必须再执行 `verify-production-release.sh`，用候选身份回执比对生产身份、
容器 ID、同一 Image ID、运行实例、完整认证会话和受保护接口。候选门禁必须显式提供
`SMART_DATA_AGENT_CANDIDATE_CONTAINER`，生产验收必须提供切流后的
`SMART_DATA_AGENT_PRODUCTION_CONTAINER`。`SMART_DATA_AGENT_RELEASE_CACHE_ROOT` 可挂载经
校验的内部 uv/npm 缓存；断网执行必须显式设置 `SMART_DATA_AGENT_RELEASE_OFFLINE=true`，
并提供本地已存在的不可变 `SMART_DATA_AGENT_TOOLCHAIN_IMAGE`。缓存根目录必须包含
`uv/`、`npm/`、`wheelhouse/`，先运行
`python scripts/release_cache_manifest.py create <缓存目录>` 生成全文件摘要清单，再把该
清单自身 SHA-256 作为 `SMART_DATA_AGENT_RELEASE_CACHE_MANIFEST_SHA256` 传入门禁。门禁
以只读方式挂载并逐文件校验缓存；缓存不完整、锁文件不一致或离线镜像仍需联网时均失败
关闭且不能生成通过回执，应用镜像构建同时使用 `--network none`。

## 9. 候选、切换、验收和回滚

候选必须与其目标服务器拓扑等价：Development 目标保持 development auth、local
object store、embedded worker；严格 Production 目标保持 OIDC、外部对象存储和独立
Worker。两者都必须使用 MySQL 8.0.18、独立回环端口、runtime/topic 安全副本、同一
Crawler Type/Source 的只读挂载和相同语义运行时合同。不得用严格 Production 组件
缺失来否定已批准的 Development 拓扑，也不得用 Development 门禁冒充严格 Production
验收。

切换前保存：

- 脱敏 `docker inspect`；
- 镜像 ID、digest、Commit 和 SHA256SUMS；
- migration ledger 和 migration attempt 回执；
- 数据库备份/恢复点；
- runtime/topic 卷备份；
- Crawler Source/mount/manifest 盘点；
- 公网 readiness、浏览器验收和日志检查结果。

以上线前恢复点和当前生产容器为前提，必须执行：

```bash
SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID=sha256:<门禁记录的工具链镜像ID> \
SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64 \
SMART_DATA_AGENT_PRODUCTION_URL=https://sda.example.com \
SMART_DATA_AGENT_CURRENT_PRODUCTION_CONTAINER=<当前生产容器名或ID> \
./scripts/capture-pre-cutover.sh <40位SHA>
```

该命令只读取公网 readiness 和 Docker 元数据，生成不含环境变量/Secret 的
`pre-cutover-snapshot.json`，固定旧容器、旧 revision、旧 Image ID 和目标候选镜像。
切流后的生产验证会再次检查旧 Image ID 仍在本机且 revision 未改变；缺少该回滚点时
生产验收失败关闭。

生产验收必须确认：精确 SHA、MySQL 8.0.18、closure、live/ready、Worker、对象存储、
语义运行时、完整认证链、canonical tenant switching、refresh、防风暴、Crawler 对应租户
非空数据、登录页及业务页 JS/CSS，以及无 migration drift、独立 500 或认证循环。

旧容器停止但保留为代码回滚单元。若新 migration 已执行，数据库回退只能使用上线前
已验证恢复点；禁止清库、删 ledger 或改 checksum。切流和生产数据动作需要独立审批，
不因代码测试通过而自动获得授权。

## 10. 变更和例外

本规范的变更必须修改版本号，说明原因、影响、验证和回滚，并通过
`check_production_development_standard.py`。例外必须记录条款、批准者、范围、到期时间、
补偿控制和撤销方式；P0 安全边界不可用普通例外绕过。

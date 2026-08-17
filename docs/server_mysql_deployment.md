# Smart Data Agent 服务器 MySQL 部署契约

## 边界

本契约只调整 SDA 镜像、挂载、依赖和启动验收，不修改服务器 MySQL 的监听、
端口、账号授权或数据，也不写入宿主机业务目录。

- MySQL 是宿主机原生 MySQL 8.x，SDA 容器通过现有 Docker 默认 bridge 访问。
- 宿主机 `/opt/smart-data-agent/src/app/data` 原样只读挂载到容器 `/app/data`。
- `/app/data/<机构名>` 是唯一原始机构目录；不存在机构文件夹时返回空目录，
  不回退到 `Origin_Data`、测试数据、首个机构或其他租户。
- `/app/Topic_Data` 是 SDA 自己生成的数据，使用独立持久卷。
- `/app/runtime` 保存附件和非结构化运行状态，使用独立持久卷。
- Compose 将 `SMART_DATA_AGENT_DATA_CRAWLER_ROOT` 固定为 `/app/data`，不允许
  通过容器环境回退到本机开发目录。
- 本机 `Origin_Data`、`Topic_Data`、`runtime`、`.git` 和测试样例不会进入
  Docker 构建上下文，也不会随镜像上传。

## 受控业务数据

仓库中的 `src/app/data/business-data-manifest.json` 是本次可部署业务 CSV 的
唯一清单。清单内文件均位于 `src/app/data/<机构名>/`，Git 克隆到默认宿主机
路径后会通过只读挂载直接呈现在 `/app/data/<机构名>/`。这些机构目录被
`.dockerignore` 排除，不进入应用镜像或远程构建缓存；未列入清单的账号、会话、
运行记录、截图、SQL 历史、原始查询目录和生成分析数据不得随发布复制。

部署前必须运行 `python3 scripts/check_server_deployment_contract.py`。检查会回读
每个清单文件的 SHA-256、行列数、直接标识字段和跨机构关系组的公共字段，确保
华兴银行与兰州银行用于表关系的汇总表能够被同一挂载目录发现。更新业务 CSV
时应同步更新清单；不得只替换文件而跳过校验。

## 必需的受保护环境变量

在 Dokploy 的 Secret/受保护环境变量中设置，不要写入 Git、镜像、Compose
明文或聊天：

```text
SMART_DATA_AGENT_AUTH_SECRET=<至少 32 字符的随机值>
SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD=<内部登录密码>
SMART_DATA_AGENT_CORS_ORIGINS=https://<SDA 对外域名>
SMART_DATA_AGENT_DATABASE_URL=mysql+pymysql://sda_app:<URL编码密码>@172.17.0.1:3306/smart_data_agent?ssl_mode=verify_ca&ssl_ca=/run/secrets/mysql_ca.pem
```

数据库密码若包含 `@`、`:`、`/`、`#` 等字符必须进行 URL 编码。Compose 默认
只读挂载宿主机 `/var/lib/mysql80/ca.pem` 到
`/run/secrets/mysql_ca.pem`；不得挂载或暴露 MySQL 服务端私钥。

## 构建前检查

```bash
python3 scripts/check_server_deployment_contract.py
docker compose -f docker-compose.server.yml config --quiet
```

第二条命令只解析配置；缺少任一必需 Secret 时应立即失败。它不连接或修改
MySQL，也不读取业务文件内容。

## 数据库分支

只允许二选一：

1. 已迁移正式 MySQL：完整保留 `platform_schema_migrations` 和所有获批正式
   机构行，排除测试/demo 租户和样例行。导入后先核对迁移 checksum、租户、
   超管、表数和各表行数，再启动 SDA；不要再次执行初始化。
2. 目标库仍为空：先显式创建 schema、正式机构、系统身份和 RBAC。每个批准的
   正式机构执行一次下面的幂等命令；它不创建演示业务数据、模型密钥或数据源密钥。

```bash
docker compose -f docker-compose.server.yml run --rm smart-data-agent \
  python scripts/provision_production.py \
  --tenant-slug "<机构名>" \
  --tenant-name "<机构名>" \
  --super-admin-subject u_super_admin \
  --super-admin-email "xujingbo-jk@qifu.com" \
  --super-admin-name "胥京波"
```

登录密码不保存在 MySQL 用户档案表中；内部单实例登录读取受保护环境变量
`SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD`。此前通过聊天传递过的密码应在
上线前轮换后再注入。

## 启动与验收

```bash
docker compose -f docker-compose.server.yml up -d --build
curl -fsS http://127.0.0.1:8787/api/live
curl -fsS http://127.0.0.1:8787/api/ready
```

验收必须同时满足：

- 镜像构建成功，容器使用 MySQL 主库且 readiness 的 database 为 ready。
- database 的角色数和用户数不为零，超级管理员可登录并保持全局身份。
- `/app/data` 可读取且为只读挂载；空目录只显示空机构目录，不导致容器退出。
- `/app/Topic_Data` 和 `/app/runtime` 可写并在重建容器后保留。
- worker 为 ready；MySQL、挂载、权限或 Secret 缺失时返回明确失败，不能使用
  Mock、SQLite、默认机构或跨租户数据掩盖错误。

## 回滚

回滚只切回上一版镜像/Compose，并保留 MySQL、`/opt/smart-data-agent/src/app/data`
以及两个持久卷。不要为代码回滚清空数据库或删除机构/Topic_Data 文件。若本次
执行过数据库导入，数据库恢复必须使用上线前单独验证过的备份，不与容器回滚混做。

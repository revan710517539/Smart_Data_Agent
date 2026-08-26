
  # 贷款数据分析Agent设计

  ## 开发与发布规范

  本项目所有开发、测试、候选和生产发布必须引用
  [`sda-production-development/v1`](DEVELOPMENT.md)。任何改动提交前运行
  `SMART_DATA_AGENT_RELEASE_SCOPE=candidate SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64 ./scripts/release-gate.sh <40位SHA>`；
  切流前运行 `./scripts/capture-pre-cutover.sh <40位SHA>` 固定旧 Image ID，切流后再运行
  `./scripts/verify-production-release.sh <40位SHA>`。构建通过或接口返回
  200 不等于已部署或生产可用。

  This is a code bundle for 贷款数据分析Agent设计. The original project is available at https://www.figma.com/design/Cs7QemQ1JsBLR6gXYw2wZs/%E8%B4%B7%E6%AC%BE%E6%95%B0%E6%8D%AE%E5%88%86%E6%9E%90Agent%E8%AE%BE%E8%AE%A1.

  ## Running the code

  Run `npm ci` to install the exact locked dependencies.

  Start the local API server:

  ```bash
  export SMART_DATA_AGENT_DATABASE_URL="mysql+pymysql://sda_dev:<password>@127.0.0.1:3306/smart_data_agent"
  npm run dev:api
  ```

  Staging and production are pinned to MySQL 8.0.18. Development and test also
  use that target by default; an existing local instance may be admitted only
  by listing its exact version in
  `SMART_DATA_AGENT_DEVELOPMENT_MYSQL_COMPATIBLE_VERSIONS`. That setting is
  rejected in staging and production.
  The API fails closed when `SMART_DATA_AGENT_DATABASE_URL` is absent or is not
  a MySQL URL. Delivered institution CSV files stay in the external Data Crawler
  directory and generated results stay in `Topic_Data/`; MySQL stores structured
  application state and governed file references.

  Keep that process running. To make a local restart survive terminal closure on macOS, use:

  ```bash
  nohup npm run dev:api > .smart-data-agent-api.log 2>&1 &
  ```

  Start the frontend development server in another terminal:

  ```bash
  npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
  ```

  The frontend proxies `/api/*` to `http://127.0.0.1:8788` in development.
  If the API is unavailable, the page keeps any cached shell visible and shows a retryable
  API error; it never treats a failed proxy request as a successful login or saved action.

  Optional SuperSonic semantic service configuration:

  ```bash
  export SMART_DATA_AGENT_SUPERSONIC_URL="https://your-supersonic-host/api/semantic/query"
  export SMART_DATA_AGENT_SUPERSONIC_API_KEY="optional-api-key"
  export SMART_DATA_AGENT_SUPERSONIC_TIMEOUT="8"
  export SMART_DATA_AGENT_SUPERSONIC_RETRIES="1"
  ```

  When `SMART_DATA_AGENT_SUPERSONIC_URL` is set, the API tries the remote
  semantic service first and falls back to the local governed semantic adapter
  if the remote service is unavailable.

  Optional API authentication mode:

  ```bash
  export SMART_DATA_AGENT_AUTH_MODE="strict"
  export SMART_DATA_AGENT_AUTH_SECRET="replace-with-a-long-random-secret"
  ```

  Development mode accepts local `X-User-Id` and `X-Tenant-Id` headers for
  prototype workflows. Strict mode requires a signed bearer token and ignores
  user or tenant values embedded in request body/query parameters.

  ## Server deployment

  The checked server contract has two governed profiles, both documented in
  `docs/server_mysql_deployment.md`:

  - The current CentOS 7 server uses direct Docker + systemd with
    `.env.server-development.example`, `scripts/server-development-container.sh`
    and `configs/deployment/smart-data-agent-docker-mss.service`. The unit name
    deliberately matches the existing server controller so deployment replaces
    it atomically after backup instead of installing a competing supervisor. It keeps
    Development authentication, local object storage and the embedded worker;
    Compose, OIDC, Redis, S3, ClamAV and a separate Worker are not prerequisites.
  - `docker-compose.server.yml` remains the stricter Production profile for a
    later environment that has OIDC, Redis TLS, KMS, external object storage,
    ClamAV and an independent Worker.

  Both profiles use `DATA_CRAWLER_MOUNT_TYPE` plus
  `DATA_CRAWLER_MOUNT_SOURCE`. Data Crawler mounts that exact Source read-write
  at `/app/data`; SDA mounts it read-only at `/app/data`. Type, Source and RW/RO
  are read back from the real containers, so equal container paths with
  different sources are rejected. Strict Compose additionally keeps
  `DATA_CRAWLER_SHARED_VOLUME` equal to the volume Source for compatibility.
  Production-equivalent validation requires the Crawler-generated versioned
  `manifest.json`.

  In both profiles:

  - `/app/Topic_Data` and `/app/runtime` use persistent writable volumes.
  - The current Development profile matches the confirmed `ssl_mode=required`
    transport. `verify_ca`/`verify_identity` profiles conditionally mount only
    the CA file read-only; the MySQL server key is never mounted.
  - Local `Origin_Data/`, `Topic_Data/`, `runtime/`, `.git/` and test fixtures are
    excluded from the Docker build context. Only the two governed schema seed
    files below `Origin_Data/` may enter the image.

  The deployment controller must inject the real values as protected environment variables. Do
  not store a database password, login password or signing secret in Git,
  Compose, the image or chat:

  ```bash
  SMART_DATA_AGENT_ENV=production
  SMART_DATA_AGENT_AUTH_MODE=strict
  SMART_DATA_AGENT_AUTH_SECRET=<long-random-secret>
  SMART_DATA_AGENT_CORS_ORIGINS=https://your-sda-host.example
  SMART_DATA_AGENT_DATABASE_URL=mysql+pymysql://sda_app:<url-encoded-password>@172.17.0.1:3306/smart_data_agent?ssl_mode=verify_ca&ssl_ca=/run/secrets/mysql_ca.pem
  SMART_DATA_AGENT_DATA_WAREHOUSE=csv
  SMART_DATA_AGENT_OBJECT_STORE=s3
  DATA_CRAWLER_SHARED_VOLUME=playwright-data-crawler-data
  DATA_CRAWLER_MOUNT_TYPE=volume
  DATA_CRAWLER_MOUNT_SOURCE=playwright-data-crawler-data
  SMART_DATA_AGENT_DATA_CRAWLER_ROOT=/app/data
  SMART_DATA_AGENT_DATA_CRAWLER_ENDPOINTS={"tenant:华兴银行":{"baseUrl":"http://playwright-data-crawler:8795","institutionId":"huaxing","institutionDirectory":"华兴银行","token":"<protected-per-institution-token>"}}
  SMART_DATA_AGENT_CSV_MAX_FILE_BYTES=134217728
  SMART_DATA_AGENT_EMBEDDED_WORKER=false
  SMART_DATA_AGENT_STATIC_ROOT=/app/dist
  ```

  `SMART_DATA_AGENT_DATA_CRAWLER_ENDPOINTS` 是机构硬隔离的权威绑定：SDA 租户、
  Data Crawler 机构 ID 和 CSV 挂载目录必须同时匹配，否则定时任务接口失败关闭。
  同机宿主进程可使用 `http://127.0.0.1:8795`；两个独立容器必须加入同一个私有网络，
  并使用 Data Crawler 服务名，不能使用容器自身的 `127.0.0.1`。每个机构必须使用
  不同令牌，不允许共享跨机构凭据。

  A genuinely empty database must be explicitly initialized before login; the
  application never invents a default production tenant or silently inserts
  demo data. Reuse `scripts/provision_production.py` for each approved formal
  institution, preserving `u_super_admin` as the single global super-admin
  subject. If the approved local MySQL database has already been migrated in
  full, skip provisioning and verify its migration ledger and row counts.

  The direct Development server also uses `SMART_DATA_AGENT_AUTO_MIGRATE=false`:
  a verified MySQL backup/isolated restore receipt is required before the
  one-time `migrate` action, and the candidate container is created stopped.
  The operator starts only the exact named candidate after approval. Changing
  the server CSV directory requires only updating `DATA_CRAWLER_MOUNT_SOURCE`
  in protected configuration; business code continues to read `/app/data`.

  Production Compose separates one-time migration and capability-preparation
  jobs from the long-running API and Worker. It
  requires enterprise OIDC, Redis TLS, KMS, object storage, ClamAV and an
  explicit egress allowlist; copy `.env.production.example` into protected
  deployment configuration and run the six release/candidate gates documented
  in `docs/server_mysql_deployment.md`. The complete model-entry, page-routing,
  scene-recognition, Skill/Memory scheduling and result-expression contract is
  documented in `docs/production_model_skill_runtime.md`.
  

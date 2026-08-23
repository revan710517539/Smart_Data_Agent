
  # 贷款数据分析Agent设计

  ## 开发与发布规范

  本项目所有开发、测试、候选和生产发布必须引用
  [`sda-production-development/v1`](DEVELOPMENT.md)。任何改动提交前运行
  `./scripts/release-gate.sh`；构建通过或接口返回 200 不等于已部署或生产可用。

  This is a code bundle for 贷款数据分析Agent设计. The original project is available at https://www.figma.com/design/Cs7QemQ1JsBLR6gXYw2wZs/%E8%B4%B7%E6%AC%BE%E6%95%B0%E6%8D%AE%E5%88%86%E6%9E%90Agent%E8%AE%BE%E8%AE%A1.

  ## Running the code

  Run `npm i` to install the dependencies.

  Start the local API server:

  ```bash
  export SMART_DATA_AGENT_DATABASE_URL="mysql+pymysql://sda_dev:<password>@127.0.0.1:3306/smart_data_agent"
  npm run dev:api
  ```

  MySQL 8.x is required for every persistent runtime, including development.
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

  ## Forgejo / Dokploy internal deployment

  The Dokploy application builds the root `Dockerfile` from the private Forgejo
  `main` branch. The checked server contract is `docker-compose.server.yml` and
  the full operator runbook is `docs/server_mysql_deployment.md`. It keeps the
  existing host-native MySQL and Data Crawler directory unchanged:

  - `/opt/palywright/examples/data-crawler/runtime-data` is mounted read-only at
    `/app/data`; production requires the versioned Crawler `manifest.json`.
  - `/app/Topic_Data` and `/app/runtime` use persistent writable volumes.
  - `/var/lib/mysql80/ca.pem` is mounted read-only; the MySQL server key is never
    mounted into the application container.
  - Local `Origin_Data/`, `Topic_Data/`, `runtime/`, `.git/` and test fixtures are
    excluded from the Docker build context. Only the two governed schema seed
    files below `Origin_Data/` may enter the image.

  Dokploy must inject the real values as protected environment variables. Do
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
  SMART_DATA_AGENT_DATA_CRAWLER_ROOT=/app/data
  SMART_DATA_AGENT_CSV_MAX_FILE_BYTES=134217728
  SMART_DATA_AGENT_EMBEDDED_WORKER=false
  SMART_DATA_AGENT_STATIC_ROOT=/app/dist
  ```

  A genuinely empty database must be explicitly initialized before login; the
  application never invents a default production tenant or silently inserts
  demo data. Reuse `scripts/provision_production.py` for each approved formal
  institution, preserving `u_super_admin` as the single global super-admin
  subject. If the approved local MySQL database has already been migrated in
  full, skip provisioning and verify its migration ledger and row counts.

  Production Compose separates one-time migration and capability-preparation
  jobs from the long-running API and Worker. It
  requires enterprise OIDC, Redis TLS, KMS, object storage, ClamAV and an
  explicit egress allowlist; copy `.env.production.example` into protected
  deployment configuration and run the six release/candidate gates documented
  in `docs/server_mysql_deployment.md`. The complete model-entry, page-routing,
  scene-recognition, Skill/Memory scheduling and result-expression contract is
  documented in `docs/production_model_skill_runtime.md`.
  

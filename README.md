
  # 贷款数据分析Agent设计

  This is a code bundle for 贷款数据分析Agent设计. The original project is available at https://www.figma.com/design/Cs7QemQ1JsBLR6gXYw2wZs/%E8%B4%B7%E6%AC%BE%E6%95%B0%E6%8D%AE%E5%88%86%E6%9E%90Agent%E8%AE%BE%E8%AE%A1.

  ## Running the code

  Run `npm i` to install the dependencies.

  Start the local API server:

  ```bash
  npm run dev:api
  ```

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
  `main` branch. For the internal single-instance environment it must have a
  named volume mounted at `/app/runtime`, and use the following non-secret
  environment values:

  ```bash
  SMART_DATA_AGENT_ENV=development
  SMART_DATA_AGENT_AUTH_MODE=development
  SMART_DATA_AGENT_DATA_WAREHOUSE=json
  SMART_DATA_AGENT_OBJECT_STORE=local
  SMART_DATA_AGENT_OBJECT_ROOT=/app/runtime/artifacts
  SMART_DATA_AGENT_CSV_SOURCE_ROOT=/app/Origin_Data
  SMART_DATA_AGENT_CSV_MAX_FILE_BYTES=134217728
  SMART_DATA_AGENT_EMBEDDED_WORKER=false
  SMART_DATA_AGENT_STATIC_ROOT=/app/dist
  ```

  Smart_Data_Agent reads only the read-only project `Origin_Data/` CSV directory.
  Each CSV is automatically listed as a raw table with a ten-row preview and
  field interpretation; no external connection or collection runtime is included.
  The CSV source directory is intentionally excluded from Git and the Docker
  build context. This internal profile is not a
  production-compliance profile: a production deployment requires the OIDC,
  PostgreSQL, Redis, KMS, object storage, ClamAV, and egress configuration in
  `docs/production_upgrade/operations_runbook.md`.
  

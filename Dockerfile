FROM node:22.14.0-bookworm-slim@sha256:1c18d9ab3af4585870b92e4dbc5cac5a0dc77dd13df1a5905cea89fc720eb05b AS frontend-build
ARG SMART_DATA_AGENT_RELEASE_OFFLINE=false
WORKDIR /workspace
COPY package.json package-lock.json ./
COPY --from=release-cache /npm /root/.npm
# The Dokploy host reaches the default npm registry unreliably.  Rewriting
# package-lock download hosts keeps reproducible lockfile versions while using
# the reachable registry mirror for the actual tarballs.
RUN if [ "${SMART_DATA_AGENT_RELEASE_OFFLINE}" = "true" ]; then \
      npm ci --ignore-scripts --offline; \
    else \
      npm config set registry https://registry.npmmirror.com \
      && npm config set replace-registry-host always \
      && npm ci --ignore-scripts; \
    fi
COPY index.html tsconfig.json vite.config.ts postcss.config.mjs ./
COPY public ./public
COPY src ./src
COPY scripts ./scripts
RUN npm run typecheck && npm run build && node scripts/check_frontend_delivery.mjs

FROM python:3.13.2-slim-bookworm@sha256:6b3223eb4d93718828223966ad316909c39813dee3ee9395204940500792b740 AS runtime-base
ARG SMART_DATA_AGENT_RELEASE_OFFLINE=false
ARG SMART_DATA_AGENT_COMMIT_SHA=unknown
ARG SMART_DATA_AGENT_BUILD_DATE=unknown
ARG SMART_DATA_AGENT_SOURCE_URL=https://xujingbo-jk-git.qifudigitech.com/revan/smart-data-agent
ARG SMART_DATA_AGENT_SOURCE_ARCHIVE_SHA256=unknown
ARG SMART_DATA_AGENT_DEPENDENCY_LOCK_SHA256=unknown
ARG SMART_DATA_AGENT_FRONTEND_ASSETS_SHA256=unknown
ARG SMART_DATA_AGENT_RELEASE_TOOLCHAIN_SHA256=unknown
LABEL org.opencontainers.image.title="Smart Data Agent" \
    org.opencontainers.image.revision="${SMART_DATA_AGENT_COMMIT_SHA}" \
    org.opencontainers.image.created="${SMART_DATA_AGENT_BUILD_DATE}" \
    org.opencontainers.image.source="${SMART_DATA_AGENT_SOURCE_URL}" \
    com.smartdataagent.source-archive-sha256="${SMART_DATA_AGENT_SOURCE_ARCHIVE_SHA256}" \
    com.smartdataagent.dependency-lock-sha256="${SMART_DATA_AGENT_DEPENDENCY_LOCK_SHA256}" \
    com.smartdataagent.frontend-assets-sha256="${SMART_DATA_AGENT_FRONTEND_ASSETS_SHA256}" \
    com.smartdataagent.release-toolchain-sha256="${SMART_DATA_AGENT_RELEASE_TOOLCHAIN_SHA256}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    SMART_DATA_AGENT_COMMIT_SHA=${SMART_DATA_AGENT_COMMIT_SHA} \
    SMART_DATA_AGENT_SOURCE_ARCHIVE_SHA256=${SMART_DATA_AGENT_SOURCE_ARCHIVE_SHA256} \
    SMART_DATA_AGENT_DEPENDENCY_LOCK_SHA256=${SMART_DATA_AGENT_DEPENDENCY_LOCK_SHA256} \
    SMART_DATA_AGENT_FRONTEND_ASSETS_SHA256=${SMART_DATA_AGENT_FRONTEND_ASSETS_SHA256} \
    SMART_DATA_AGENT_RELEASE_TOOLCHAIN_SHA256=${SMART_DATA_AGENT_RELEASE_TOOLCHAIN_SHA256} \
    SMART_DATA_AGENT_ENV=production \
    SMART_DATA_AGENT_STATIC_ROOT=/app/dist \
    SMART_DATA_AGENT_DATA_WAREHOUSE=csv \
    SMART_DATA_AGENT_DATA_CRAWLER_ROOT=/app/data \
    SMART_DATA_AGENT_OBJECT_ROOT=/app/runtime/artifacts \
    SMART_DATA_AGENT_NON_STRUCTURED_ROOT=/app/runtime/non_structured
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY pyproject.toml requirements.runtime.lock README.md ./
COPY backend ./backend
COPY configs ./configs
COPY integrations ./integrations
# Only bundle governed schema seeds. Delivered business CSV files may contain
# customer data and are mounted read-only at runtime.
COPY Origin_Data/__init__.py Origin_Data/metric_dictionary_seed.json ./Origin_Data/
COPY scripts ./scripts
COPY --from=frontend-build /workspace/dist ./dist
COPY --from=release-cache /wheelhouse /release-cache/wheelhouse
RUN if [ "${SMART_DATA_AGENT_RELEASE_OFFLINE}" = "true" ]; then \
      pip install --no-cache-dir --no-index --find-links=/release-cache/wheelhouse -r requirements.runtime.lock; \
    else \
      pip install --no-cache-dir --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.runtime.lock; \
    fi \
    && pip install --no-cache-dir --no-deps --no-build-isolation . \
    && python scripts/check_mysql_sql_closure.py \
    && test "$(python scripts/release_identity.py frontend-hash dist)" = "${SMART_DATA_AGENT_FRONTEND_ASSETS_SHA256}"
RUN mkdir -p /app/data /app/runtime/artifacts /app/runtime/non_structured /app/Topic_Data \
    && chown -R app:app /app
USER app
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/ready', timeout=3)"
CMD ["smart-data-agent-asgi", "--host", "0.0.0.0", "--port", "8787", "--workers", "1", "--static-root", "/app/dist"]

FROM runtime-base AS runtime

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /workspace
COPY package.json package-lock.json ./
# The Dokploy host reaches the default npm registry unreliably.  Rewriting
# package-lock download hosts keeps reproducible lockfile versions while using
# the reachable registry mirror for the actual tarballs.
RUN npm config set registry https://registry.npmmirror.com \
    && npm config set replace-registry-host always \
    && npm ci --ignore-scripts
COPY index.html tsconfig.json vite.config.ts postcss.config.mjs ./
COPY public ./public
COPY src ./src
RUN npm run typecheck && npm run build

FROM python:3.13-slim-bookworm AS runtime-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SMART_DATA_AGENT_ENV=production \
    SMART_DATA_AGENT_STATIC_ROOT=/app/dist \
    SMART_DATA_AGENT_JSON_WAREHOUSE_PATH=/app/data/mock/semantic_datasets.json \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY pyproject.toml requirements.runtime.lock README.md ./
COPY backend ./backend
COPY configs ./configs
# Only bundle deterministic demo/seed data. Crawler exports and source
# downloads may contain customer data and are kept on the runtime volume.
COPY data/__init__.py data/metric_dictionary_seed.json ./data/
COPY data/mock ./data/mock
COPY scripts ./scripts
COPY --from=frontend-build /workspace/dist ./dist
RUN pip install --no-cache-dir --index-url https://pypi.tuna.tsinghua.edu.cn/simple "setuptools>=68" \
    && pip install --no-cache-dir --no-build-isolation --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.runtime.lock \
    && pip install --no-cache-dir --no-deps --no-build-isolation .
RUN mkdir -p /app/runtime /app/data/智能运营 && chown -R app:app /app
USER app
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/ready', timeout=3)"
CMD ["smart-data-agent-asgi", "--host", "0.0.0.0", "--port", "8787", "--db", "/app/runtime/smart-data-agent.sqlite", "--workers", "1", "--static-root", "/app/dist"]

FROM runtime-base AS crawler-runtime
USER root
RUN python -m playwright install --with-deps chromium \
    && chown -R app:app /app /ms-playwright
USER app
HEALTHCHECK NONE
CMD ["smart-data-agent-worker", "--db", "/app/runtime/smart-data-agent.sqlite", "--worker-id", "crawler-worker"]

FROM runtime-base AS runtime

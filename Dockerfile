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
COPY scripts ./scripts
RUN npm run typecheck && npm run build

FROM python:3.13-slim-bookworm AS runtime-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
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
RUN pip install --no-cache-dir --index-url https://pypi.tuna.tsinghua.edu.cn/simple "setuptools>=68" \
    && pip install --no-cache-dir --no-build-isolation --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.runtime.lock \
    && pip install --no-cache-dir --no-deps --no-build-isolation . \
    && python scripts/check_mysql_sql_closure.py
RUN mkdir -p /app/data /app/runtime/artifacts /app/runtime/non_structured /app/Topic_Data \
    && chown -R app:app /app
USER app
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/ready', timeout=3)"
CMD ["smart-data-agent-asgi", "--host", "0.0.0.0", "--port", "8787", "--workers", "1", "--static-root", "/app/dist"]

FROM runtime-base AS runtime

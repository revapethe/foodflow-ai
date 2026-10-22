# syntax=docker/dockerfile:1
FROM scratch AS python-sources
COPY src/ /app/src/
COPY sql/ /app/sql/
COPY data/raw/ /app/data/raw/
COPY api/ /app/api/
COPY deploy/start.sh /app/deploy/start.sh

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build/frontend
ENV NEXT_TELEMETRY_DISABLED=1 FOODFLOW_STANDALONE=1
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=build_ca,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build \
    && mkdir -p /runtime/usr/local/bin /runtime/build/frontend/.next \
    && cp /usr/local/bin/node /runtime/usr/local/bin/node \
    && cp -a .next/standalone/. /runtime/build/frontend/ \
    && cp -a .next/static /runtime/build/frontend/.next/static

FROM python:3.12-slim-bookworm AS python-build
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.txt requirements-api.txt requirements-ml.txt ./
RUN --mount=type=secret,id=build_ca,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    /opt/venv/bin/python -m pip install --no-cache-dir --upgrade 'pip>=26.2,<27' \
    && /opt/venv/bin/python -m pip install --no-cache-dir -r requirements-ml.txt \
    && /opt/venv/bin/python -m pip check
COPY --from=python-sources /app/ /build/
# Combine build steps to avoid large duplicate dependency layers on vfs builders.
RUN --mount=type=secret,id=build_ca,mode=0444 \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && if [ -f /run/secrets/build_ca ]; then printf 'Acquire::https::CaInfo "/run/secrets/build_ca";\n' > /etc/apt/apt.conf.d/99build-ca; fi \
    && apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -f /etc/apt/apt.conf.d/99build-ca \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 foodflow \
    && useradd --uid 10001 --gid foodflow --create-home foodflow \
    && /opt/venv/bin/python -m src.pipeline build \
    && /opt/venv/bin/python -m src.intelligence.train --output /build/artifacts/intelligence.json \
    && chown -R foodflow:foodflow /build \
    && chmod a-w /build/warehouse/foodflow.db \
    && ln -s /build /app
FROM python-build AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000
WORKDIR /app
COPY --from=frontend-build /runtime/ /
USER foodflow
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','10000')+'/api/health',timeout=4).close()"
CMD ["bash", "/app/deploy/start.sh"]

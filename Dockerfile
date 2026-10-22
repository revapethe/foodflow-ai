# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build/frontend
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=build_ca,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build && npm prune --omit=dev --no-audit --no-fund

FROM python:3.12-slim-bookworm AS python-build
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.txt requirements-api.txt ./
RUN --mount=type=secret,id=build_ca,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    /opt/venv/bin/python -m pip install --no-cache-dir --upgrade 'pip>=26.2,<27' \
    && /opt/venv/bin/python -m pip install --no-cache-dir -r requirements-api.txt \
    && /opt/venv/bin/python -m pip check
COPY src/ ./src/
COPY sql/ ./sql/
COPY data/raw/ ./data/raw/
# Build only from bundled CSVs. Never regenerate or edit the source datasets.
RUN /opt/venv/bin/python -m src.pipeline build

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000
WORKDIR /app
RUN --mount=type=secret,id=build_ca,mode=0444 \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && if [ -f /run/secrets/build_ca ]; then printf 'Acquire::https::CaInfo "/run/secrets/build_ca";\n' > /etc/apt/apt.conf.d/99build-ca; fi \
    && apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -f /etc/apt/apt.conf.d/99build-ca \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 foodflow \
    && useradd --uid 10001 --gid foodflow --create-home foodflow
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY --from=python-build /opt/venv /opt/venv
COPY --chown=foodflow:foodflow --from=frontend-build /build/frontend /app/frontend
COPY --chown=foodflow:foodflow --from=python-build /build/src /app/src
COPY --chown=foodflow:foodflow --from=python-build /build/warehouse /app/warehouse
COPY --chown=foodflow:foodflow api/ /app/api/
COPY --chown=foodflow:foodflow deploy/start.sh /app/deploy/start.sh
RUN chmod a-w /app/warehouse/foodflow.db
USER foodflow
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','10000')+'/api/health',timeout=4).close()"
CMD ["bash", "/app/deploy/start.sh"]

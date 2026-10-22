> This is the historical Phase 1 deployment record. For the current platform, updating an existing free service, release checks, and rollback, use [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md). Do not reapply the old Blueprint branch blindly.

# Publish the Phase 1 demo on Render

This deploys the existing Next.js dashboard and FastAPI read-only analytics as **one Docker web service**. It serves the bundled synthetic delivery data; no AWS, Snowflake, OpenAI, local installation, or external database is needed. Main and Phase 2 are unchanged.

## Browser-only publishing

1. Make sure the reviewed `feature/phase-1-intelligence-dashboard` branch, including `Dockerfile`, `render.yaml`, the frontend, and API, is pushed to `revapethe/foodflow-ai` on GitHub. A branch that exists only in this Codex workspace is not visible to Render. Codex can push the prepared branch when authorized; you do not need Git installed locally.
2. Sign in to [Render](https://dashboard.render.com), connect GitHub, and grant access to this repository.
3. Choose **New → Blueprint**, select this repository and **feature/phase-1-intelligence-dashboard**, and use the root `render.yaml` file. Review Render's configuration validation and the service plan before approving creation.
4. The blueprint requests a **Free** Docker web service, port **10000**, and health check **/api/health**. Automatic deploys are disabled. If the free plan is unavailable for your account, choose a supported plan explicitly after reviewing its cost; do not provision a paid plan accidentally.
5. Approve the initial deployment. After Render reports the service healthy, open the HTTPS URL displayed on the service page. That platform-generated URL is the demo address; it is not a localhost or Codex preview link. No URL exists until the service is created.

If the Blueprint UI is unavailable, create **New → Web Service** with the same repository/branch, Docker runtime, root directory unset, Dockerfile `./Dockerfile`, build context `.`, port environment variable `PORT=10000`, health path `/api/health`, and automatic deployment disabled. Let the Dockerfile provide the start command; do not set a separate npm-only start command.

## What the service runs

- A multi-stage build installs locked frontend dependencies, builds Next.js, removes frontend development dependencies, and prepares the Python environment.
- The warehouse is built from the seven preserved CSVs using `src.pipeline build`, not `generate` or `all`. The image never includes local `.env` files, virtual environments, Git metadata, node_modules from the workspace, or the current local warehouse.
- The final image runs as an unprivileged user. The bundled database file has write permission removed, and FastAPI opens it in read-only mode.
- Next.js listens on `0.0.0.0:$PORT`. FastAPI listens only on `127.0.0.1:8000` inside the same container. Relative `/api/*` browser requests go through Next.js to the private backend. No CORS relaxation or public backend URL is needed.
- Startup waits for FastAPI readiness. If either service exits, its companion is stopped and the container exits so hosting supervision can restart it. Both services write logs to Render's log stream.
- Docker and Render health checks use `/api/health` through Next.js. This checks the backend and warehouse, rather than just an open port.

Do not set `FOODFLOW_API_URL` or `FOODFLOW_DB_PATH` for the standard demo. Their default addresses and image paths already match. The Next.js proxy destination is captured during its production build; changing it requires rebuilding.

## Check the live demo

After Render supplies the URL:

1. Confirm the dashboard shows **3,000 orders**, **2,645 delivered**, and **$144,709.13 delivered revenue** with all filters cleared.
2. Select **Denver**: expect **475 delivered orders** and **$28,195.65 revenue**.
3. Restrict Denver to **March 1–June 30, 2025**: expect **145 delivered orders**, **167 total orders**, and **$8,428.55 revenue**.
4. Switch revenue/orders charts, hover tooltips, inspect rankings and product units, and export daily data. Check the layout on a narrow browser window.
5. Open the service URL with `/api/health` appended: expect `{"status":"ok"}`.

These values come from the actual bundled warehouse. The datasets are synthetic; no operational inventory, suppliers, forecasts, or model accuracy results are implied.

## Limits and operations

This is a public, read-only portfolio demo without application authentication. Only bundled synthetic data should be included. Do not add real customer data, credentials, or write endpoints without a separate deployment review. Cloud and AI integrations remain disabled/unconfigured. The existing Streamlit apps and ETL stay in the repository, but this service runs the Next.js dashboard only.

The free service may sleep when idle and take time to start again. The exact behavior and quotas depend on Render's current offering. The database is reproducibly bundled in the image, so no paid persistent disk is needed. Container filesystem changes are ephemeral and are not an ETL scheduling solution. Rebuild/redeploy explicitly when replacing the bundled source data. This setup does not implement Phase 2 or the full production deployment work planned for Phase 5.

Inspect Render logs for Python startup errors, Next.js port announcements, and health-check failures. A failed frontend build means there is no deployable image; do not interpret a running builder or a static landing response as readiness. Roll back through Render's service controls to a previously validated deploy if needed.

## Container validation in Codex

Standard build/run commands (for the agent/cloud environment, not required on your machine):

```bash
docker build -t foodflow-phase1-demo:review .
docker run --name foodflow-demo-review -d -p 127.0.0.1:10000:10000 foodflow-phase1-demo:review
```

When building behind an approved enterprise TLS proxy, the Dockerfile supports an optional BuildKit secret named `build_ca` containing the trusted CA bundle. It is mounted only during dependency installation and is not embedded in the final image. Proxy routing and hostname resolution may require build-host configuration in Codex. Never disable TLS verification or copy private proxy configuration into the deployment repository. Normal Render builds do not need this secret.

## Validation results for this change

- Docker image built successfully with Node 22 and Python 3.12, preserving TLS, registry integrity, and apt signature checks.
- The running image passed **8 Chromium tests** and **10 live warehouse reconciliation cases** using its own freshly built warehouse and public frontend port.
- Existing Python suite: **24 passed**; the upstream test-client deprecation warning remains.
- Runtime user: **10001**; database write access: **false**; Docker health: **healthy**.
- Test container memory limit: **512 MB**, CPU limit: **1**; no OOM event observed during the functional checks. This is not a sustained load test or a guarantee for any hosting plan.
- Terminating the private API caused the container to exit and shut down its companion; restarting the container restored the service.
- Invalid or conflicting `PORT` values are rejected before startup.
- No local `.env`, Git metadata, or mounted build CA is present in the runtime image.
- Render account connection, server-side Blueprint validation, deployment, and hosted HTTPS browser checks have **not** been performed. Fetching Render's schema from this environment returned an outbound 403, so the Blueprint must also be reviewed by Render before approving service creation.

The Docker build in this Codex machine required its existing proxy routing, explicit proxy-host resolution, and its supplied CA bundle via a temporary BuildKit secret. These environment-specific values were not saved in the repository or final image. Render's normal builder should use its own network and certificate trust configuration.

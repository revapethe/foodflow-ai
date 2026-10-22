# Release, deployment and rollback runbook

## Scope

The supported no-cost demo is one Docker web service: Next.js, private FastAPI, a built SQLite warehouse, and a precomputed evaluated artifact. It does not require a hosted PostgreSQL database, OpenAI, AWS, Snowflake, a persistent disk, or Airflow. Existing free-service and CI quotas remain account-dependent; if an included quota is unavailable, stop rather than upgrading. This runbook does not authorize a paid plan.

The Phase 5 feature branch is `feature/phase-5-release-readiness`. Main and the existing Render service are not modified automatically. Earlier phase documents describe their own historical state; this document is the current operating reference.

## Before release

1. Review the feature diff and record its full Git commit. Preserve all seven source CSVs, any user batches, and existing warehouse contents. Use the existing checkout; a new worktree is unnecessary.
2. Verify Python 3.12/Node 22 dependencies against `requirements-test.lock`, the compatible requirement declarations, and `frontend/package-lock.json`. The runtime lock is the smaller Docker environment; PostgreSQL/cloud-contract test dependencies are in the test lock.
3. For a fresh workspace only, build a missing SQLite warehouse with `python -m src.pipeline build`. Never use `generate`/`all` on existing tracked datasets. Inspect a used warehouse before explicitly replacing its data. Train a matching artifact with `python -m src.intelligence.train`; training is not part of an API request.
4. Start only the local development PostgreSQL service needed for integration tests. See PHASE2.md for its loopback binding, named volume, reader grants, and source publication. Never expose development trust authentication publicly.
5. Run the validation commands below. Stop on failures, missing required evidence, or skipped PostgreSQL integration tests. Do not relabel those outcomes as passes.

Commands below run inside the cloud environment; the user need not install anything on their own computer.

```bash
cd /workspace/foodflow-ai
.venv-api/bin/python -m pip install -r requirements-test.lock -r requirements-test.txt -r requirements-postgres.txt
.venv-api/bin/python -m pip check
.venv-api/bin/python scripts/check_dependencies.py --lock requirements-test.lock
FOODFLOW_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:55432/foodflow .venv-api/bin/python -m pytest -q
FOODFLOW_PYTHON=.venv-api/bin/python CHROMIUM_PATH=/usr/bin/chromium bash scripts/validate_web.sh
npm audit --prefix frontend
```

`validate_web.sh` reserves free ports 8005/3005, builds in `.next-release`, starts its own API/web children, checks readiness, runs Playwright, reconciles historical and assistant results with SQLite, checks forecast evidence, and stops its own children on exit. It refuses occupied ports rather than stopping existing services. Override `FOODFLOW_API_PORT`, `FOODFLOW_WEB_PORT`, `FOODFLOW_NEXT_DIST_DIR`, `FOODFLOW_REPORT_DIR`, or `FOODFLOW_PYTHON` for another isolated session. Use Playwright's installed Chromium if `/usr/bin/chromium` is unavailable. Incidental generated Next.js types/config changes should not overwrite unrelated user edits or be committed as product changes.

To audit Python without adding auditor dependencies to the application environment, create a separate temporary venv and use its `pip-audit --strict -r requirements-test.lock --no-deps --disable-pip`. Supply a writable `--cache-dir` in restricted workspaces. Both lock files are exact version snapshots, not hash-complete or cross-platform locks. Pip-audit explicitly recommends distribution hashes as further hardening. Keep TLS, wheel/registry integrity, and package-signature verification enabled; audit results are time-limited observations, not a vulnerability guarantee.

## Docker release gate

For a clean reviewed commit:

```bash
docker build --build-arg FOODFLOW_REVISION="$(git rev-parse HEAD)" -t foodflow-release:check .
.venv-api/bin/python scripts/check_container.py --image foodflow-release:check --expected-revision "$(git rev-parse HEAD)" --report logs/release/container-check.json
```

If building uncommitted work, explicitly mark `FOODFLOW_REVISION=working-tree`; do not label modified code as the previous clean commit. This was the marker used for the local Phase 5 validation image. The default revision is `unknown` when neither a build argument nor Render commit metadata is supplied. `/api/version` reports identity/capabilities; `/api/health` separately requires warehouse readiness. Render supplies `RENDER_GIT_COMMIT`, which takes precedence over the generic build marker.

The container check creates uniquely named, temporary test containers bound to loopback. It reconciles actual HTTP results, tests the non-root user and read-only database, terminates only its own container's API to test companion shutdown, checks restart recovery and invalid PORT rejection, and removes its containers even on failure. It does not delete source data, images, unrelated containers, or volumes. Use `DOCKER_CONFIG=/tmp/foodflow-docker-config` in this workspace if the default Docker configuration directory is read-only.

Resource limits are 512 MB and one CPU. Passing these functional checks is not a sustained load test or an availability/SLA guarantee. Some nested Docker builders use the `vfs` storage driver and duplicate parent filesystems per layer. Check free disk before a build. Only obsolete build cache may be pruned after inspecting its ownership/use; never prune user volumes or unrelated running services. The Dockerfile reuses the Python environment and packages Next.js standalone output to reduce dependency copies.

For approved TLS proxies, the existing optional BuildKit `build_ca` secret supplies the trusted CA during installation only. Do not disable TLS or copy proxy credentials, CA files, `.env`, or Git metadata into the image. Normal Render builds use their own trust configuration.

## CI policy and what has been verified

`.github/workflows/release-validation.yml` is manual (`workflow_dispatch`) with read-only repository permission, pinned action commits, timeout/concurrency limits, and short-lived evidence artifacts. It runs PostgreSQL tests and idempotent ETL, source-preserving SQLite build, offline training, production frontend/browser checks, release reconciliation, and dependency audits. Docker validation is an optional input because it uses more runner minutes. There are no deployment credentials, registry uploads, scheduled runs, or new push/PR triggers. The older Phase 2 workflow remains intact.

**GitHub must have a dispatchable workflow on its default branch before the usual Actions “Run workflow” UI is available.** This phase leaves main unchanged, so it does not claim that the feature-only workflow can already be dispatched. After separately reviewing and merging the workflow, it can be run against a selected reviewed ref using the account's included runner quota. No GitHub-hosted workflow was triggered here. The equivalent commands were executed in the cloud workspace; workflow syntax was checked with YAML parsing and Actionlint. Check the repository's Actions quota/billing settings before choosing a hosted run. If free quota is unavailable, use the cloud-workspace commands and do not enable paid minutes.

Evidence is under the ignored `logs/release/` directory locally, or the seven-day `release-validation` artifact for an actual hosted run. It includes logs, heldout evaluation, and release-check JSON. Do not add credentials or private data to retained artifacts. A green hosted badge must refer to a real completed run, not this workflow definition.

## Browser-only Render deployment

1. Open the existing `foodflow-intelligence-demo` service in Render. Record its current successful deployment/commit so you can return to it.
2. Under **Settings → Branch → Edit**, select the reviewed `feature/phase-5-release-readiness` branch (or an explicitly reviewed release ref). Keep **Docker** runtime and **Free** instance. Leave Docker Command empty; the image supplies `/app/deploy/start.sh`. Keep auto-deploy off. Do not create another paid service or database.
3. Under **Deploys**, choose **Manual Deploy → Deploy latest commit**. Watch build/runtime logs. A successful build is not the same as a Live/healthy service.
4. Once Live, open the HTTPS URL Render displays. If the free service slept, allow it to wake. A raw `127.0.0.1` or `0.0.0.0` URL points at your own machine and will not open the cloud workspace.
5. Check `/api/health`, `/api/version`, all-city KPIs, the historical forecast origin, and the assistant. With cleared filters, expect 3,000 orders, 2,645 delivered, and $144,709.13 revenue. Denver should show 475 delivered/$28,195.65; Denver March–June 2025 should show 145 delivered/$8,428.55. Ask “What is total revenue?” and inspect its SQL. Unsupported “Why is profit falling?” must clarify.
6. From the cloud workspace, optionally run `scripts/check_release.py --web-url <Render HTTPS URL> --expected-revision <reviewed full commit> --report logs/release/hosted-check.json`. It compares with the local bundled evidence, so use the same reviewed dataset/artifact. A sleeping free service can exceed the script's timeout; wake it and retry after it becomes healthy.

For an existing Blueprint-managed service, do not blindly reapply the old Phase 1 `render.yaml`: it records the original branch. This phase preserves that file rather than silently moving the live service. First-time service creation and historical settings are recorded in [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md).

## Rollback and operational recovery

If build/deploy/health or functional checks fail, keep or restore the previously validated deployment using Render's deployment controls. If redeploying a prior commit, first restore the service's previous branch/commit selection and keep automatic deployment off; otherwise a later manual deploy may advance to an unreviewed tip. Verify `/api/version` and the same functional checks after rollback. Bundled SQLite and artifacts are immutable build outputs, so rollback requires no destructive migration.

For workspace PostgreSQL failures, use PHASE2.md: inspect durable run/quality logs and publication status, fix the source/contract problem, and retry the transaction-owning loader. Never delete the named volume to fix an ETL failure. A stale model artifact should produce `stale`, not guessed forecasts; explicitly retrain after validating the new publication.

For port/startup failures, inspect web/API logs and whether a Docker Command override was set. Native Render services do not have the Docker image's `/app` layout; use Docker runtime for this runbook. For proxy errors, keep the API private and check the build-time Next.js rewrite. For stale UI assets, refresh the browser after confirming the deployed revision. Do not substitute a paid host or external tunnel for a failed internal preview.

## Limits that remain

This is a synthetic-data portfolio service. It has no application authentication, production ingestion scheduler, backup service, production secrets manager, labeled anomaly evaluation, current real-world demand data, stock/supplier feeds, or sustained capacity test. Those are separate requirements before handling real operational data. Optional AWS/Snowflake/OpenAI/Airflow/Spark configurations remain outside the verified free path. A free account's uptime/build quotas and platform capabilities can change; this work does not promise perpetual free hosting.

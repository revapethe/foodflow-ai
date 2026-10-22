# Phase 5: release verification and operations

Phase 5 adds reproducible dependency snapshots, a complete manual CI definition, repeatable release/container gates, build identity, current architecture documentation, and a deployment/rollback runbook. It preserves the existing datasets, ETL, dashboard, evaluated models, bounded assistant, and legacy integrations. Main and the live Render service are unchanged by this branch.

## Changes

- `requirements-runtime.lock`: exact tested Linux/Python 3.12 Docker dependencies. Docker installs the lock and compatible declarations, then verifies the complete installed distribution set.
- `requirements-test.lock`: exact API/ML/PostgreSQL/offline-contract test environment. `scripts/check_dependencies.py` rejects missing, extra, duplicate, unpinned, or version-drifted entries.
- `/version` (publicly proxied as `/api/version`): revision/capabilities metadata, with Render's commit overriding the generic image marker. No database connection or configuration-secret dump is needed for this metadata endpoint. Warehouse health stays separate.
- `scripts/check_release.py`: reconciles ten historical API cases with read-only SQLite, compares two markets' forecasts with the evaluated artifact, independently recomputes heldout errors/coverage, checks chronology and future dates, reconciles three assistant scopes, and checks abstention. An expected revision can be required. It never executes SQL obtained over HTTP.
- `scripts/validate_web.sh`: isolated production build, typecheck, API/web startup, Playwright, reconciliation, logs, and cleanup of its own processes.
- `scripts/check_container.py`: temporary-container validation under 512 MB/one CPU, non-root/read-only assertions, API termination/companion shutdown, restart recovery, and conflicting-port rejection. Only its own temporary containers are removed.
- `.github/workflows/release-validation.yml`: manually invoked full-platform validation with pinned action commits, PostgreSQL, audits and optional Docker gate. It has no deployment token, registry upload, scheduler, or new automatic push/PR trigger. The existing Phase 2 workflow is preserved.
- [Architecture diagrams and data contracts](docs/ARCHITECTURE.md), refreshed README, and [release/deployment/rollback runbook](docs/RELEASE_RUNBOOK.md).

## Validation evidence

The local suite passed 91 Python tests, including new guards that reject tampered metrics, coverage, chronology, missing/duplicate dates, NaNs, and dependency drift. PostgreSQL integration tests ran against disposable test databases on the workspace development server; there were no integration skips. The upstream Starlette/httpx deprecation warning remains.

The isolated production build/typecheck passed, as did 14 Chromium tests. The release gate passed ten historical warehouse/filter cases, two evaluated market forecasts, three assistant SQL reconciliations, and an unsupported-question abstention check. The installed test environment matched all 74 locked distributions. Python lock audit and frontend npm audit reported zero known vulnerabilities. Exact version locks are not distribution-hash locks; the auditor recommends hashes as further hardening.

Workflow YAML parsing and Actionlint v1.7.7 passed. Actionlint's official release archive checksum was verified before use. The workflow's action commit references were resolved from their official upstream repositories. GitHub-hosted CI was not run, and no hosted badge, deployment, or free-quota availability is claimed. Standard manual dispatch requires the workflow on the default branch; main is deliberately unchanged here.

The Docker container gate also passed the same warehouse/model/assistant release checks under 512 MB/one CPU, verified UID 10001 and the read-only file, confirmed API/companion shutdown and restart recovery, and rejected a conflicting PORT. No OOM kill was observed. These are functional checks, not a sustained load test. Temporary validation containers were removed.

The Docker image is built from the working tree with a `working-tree` revision marker rather than falsely labeling modified code as the previous commit. Render deployments should report their actual `RENDER_GIT_COMMIT`; clean manual image builds should supply the reviewed commit argument. See the runbook for the full commands and limits. No live Render deployment is performed by the checks.

## Run the verified checks

Use the existing cloud checkout; no installation on your own computer is required. Follow [RELEASE_RUNBOOK.md](docs/RELEASE_RUNBOOK.md) for dependencies, local PostgreSQL prerequisites, exact commands, optional CI, browser-only Render deployment, and rollback. A workspace browser needs platform port forwarding; raw localhost links are internal checks only.

Current branch: `feature/phase-5-release-readiness`. Completing this phase does not merge main, move Render's live branch, provision a paid database, or activate a production ingestion schedule. Review the changes before choosing a separate rollout.

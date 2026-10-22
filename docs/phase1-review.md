# Phase 1 verification and review

All changes remain on `feature/phase-1-intelligence-dashboard`. No Phase 2 work or main-branch updates were performed.

## Integration findings and fixes

An expanded browser test exposed intermittent 503/500 responses during overlapping filter requests. FastAPI can enter a synchronous dependency, execute its endpoint, and close the dependency on different worker threads. SQLite's default thread check rejected that handoff. Each request now has its own connection with `check_same_thread=False`; read-only URI mode and `query_only` remain enforced. Connections are never shared across requests. New regressions exercise 32 overlapping requests, deterministic worker handoff, and rejected writes.

The frontend was verified through the actual Next.js proxy to FastAPI and the existing warehouse. `scripts/verify_phase1.py` independently queries SQLite and compares every KPI, daily series, status count, restaurant ranking, and product series for ten selections: all data, each of six cities, Denver with a date range, one inclusive calendar day, and a real empty date range. All ten passed without mocks or writes.

| Selection | All orders | Delivered orders | Delivered revenue |
|---|---:|---:|---:|
| All data | 3,000 | 2,645 | $144,709.13 |
| Denver | 528 | 475 | $28,195.65 |
| Denver, March 1–June 30, 2025 | 167 | 145 | $8,428.55 |

The seven CSVs and existing warehouse retain identical SHA-256 checksums before/after review. Existing ETL, source, cloud code, SQL models, and Streamlit applications are unchanged.

## UI review

- Responsive KPI cards and charts render without page overflow at 320, 390, 768, and 1440px. The restaurant table scrolls within its own focusable region on small screens.
- Added compact mobile section navigation, strengthened muted text contrast, and retained a consistent green/neutral visual hierarchy. This is a visual and functional review, not a full accessibility certification.
- Currency now preserves cents. “Delivery completion” replaces the potentially ambiguous “Fulfillment rate”; its definition remains delivered/all orders.
- City and inclusive date filters apply consistently to cards, tables, charts, reviews, and exported CSV rows. Loading/error states hide stale results; exports are disabled while loading or failed. Requests time out after 15 seconds and can be retried.
- Revenue/orders switching, chart tooltip display, product bars, ranking rows, export contents, invalid dates, empty results, and recovery from a simulated service failure are exercised in Chromium.
- Daily chart segments use linear interpolation to avoid implying smoothed model estimates. Missing days are explicitly not imputed. The demand outlook remains an illustration clearly marked unavailable; no forecasts or accuracy claims exist.

## Dependency security audit

The complete frontend dependency graph initially reported two affected packages: Next.js and its nested PostCSS 8.4.31. PostCSS advisories included CSS stringify XSS and source-map file disclosure (GHSA-qx2v-qp2m-jg93, GHSA-6g55-p6wh-862q, GHSA-fxqj-rqcc-2cmp, GHSA-r28c-9q8g-f849). A scoped npm override now selects PostCSS **8.5.31** under Next.js, preserving Next.js 15.5.28. The regenerated lockfile, optimized build, TypeScript check, and browser tests pass with this version. Final `npm audit` over production and development dependencies reports **zero known vulnerabilities**. Remove the override when a compatible Next.js release directly uses a patched PostCSS version.

The Python audit initially identified vulnerable `certifi` 2025.1.31 and `pip` 25.0.1 in the existing shared virtual environment. The dedicated Phase 1 `.venv-api` uses certifi **2026.10.19** and pip **26.2.2**. `pip-audit` over its entire installed dependency set reports **zero known vulnerabilities**, and `pip check` passes. The API requirements enforce the patched certificate bundle; setup instructions upgrade pip before installing dependencies. No TLS or artifact verification was disabled.

### Unresolved optional cloud environment constraint

The existing `.venv` was updated to patched pip/certifi during investigation, but its optional **dbt-snowflake 1.12.3** requires `certifi<2025.4.26`. Consequently `pip check` in that legacy shared environment reports a version conflict. The registry's latest adapter is 1.12.3; 1.11.6 has the same upper bound. We did not downgrade the patched certificate store, force a resolver override, change cloud manifests, or claim live dbt/Snowflake readiness. Phase 1 runs in `.venv-api` without dbt and has no dependency conflicts. A compatible adapter/trust-bundle solution remains necessary before using the optional cloud/dbt workflow. This does not block the verified Phase 1 dashboard.

One upstream Starlette warning about httpx test-client deprecation remains; all tests execute successfully. Authentication, rate limiting, public deployment hardening, and live cloud integration are still outside Phase 1. Audit results describe the installed versions and the advisory database at review time, not a guarantee against future vulnerabilities.

## Repeat the checks

From the repository root, with the two services running as documented in PHASE1.md:

```bash
.venv-api/bin/python -m pytest -q
.venv-api/bin/python -m pip check
.venv-api/bin/python scripts/verify_phase1.py
npm run build --prefix frontend
npm run typecheck --prefix frontend
CHROMIUM_PATH=/usr/bin/chromium npm run test:e2e --prefix frontend
npm audit --prefix frontend --cache /tmp/foodflow-npm-cache --fetch-retries=0 --fetch-timeout=20000
```

Restart the Next.js production process after rebuilding. Omit `CHROMIUM_PATH` if using Playwright's installed browser.

For Python security scanning, use a separate audit-tool environment:

```bash
python -m venv /tmp/foodflow-audit-venv
/tmp/foodflow-audit-venv/bin/python -m pip install pip-audit
/tmp/foodflow-audit-venv/bin/pip-audit --path .venv-api/lib/python3.12/site-packages --cache-dir /tmp/foodflow-pip-audit-cache --progress-spinner off
```

The path above is for Python 3.12 on Linux; use the target environment's site-packages path on other systems.

## Final outcomes

- 24 Python tests passed.
- 8 Chromium browser tests passed.
- 10 live warehouse/proxy reconciliation selections passed.
- Production build and TypeScript checks passed.
- Phase 1 Python dependency consistency and both dependency security audits passed.
- Optional legacy dbt certificate constraint and upstream test-client deprecation remain as described above.

## Cloud preview follow-up

The initial frontend scripts bound Next.js to loopback, which prevented direct container-network access. `dev` and `start` now bind `0.0.0.0:3000`. `scripts/start_preview.sh` manages both services and captures logs. The backend stays private behind the Next.js proxy. Direct HTTP and Chromium checks over the container network now pass with actual warehouse data. This is application-side preview readiness; Codex must still provide a forwarded port-3000 URL. The observed user error (“127.0.0.1 refused to connect”) indicates a loopback URL rather than a forwarded cloud address. No supported preview registration/gateway-control tool is exposed in this session.

The first attempt to run browser tests against the private container IP used the environment’s outbound proxy and received its 403 “Domain forbidden” response. Direct private-network checks and a Chromium run without the outbound proxy passed; the standard eight-test suite passed against loopback. No external network policy was broadened. Main, datasets, the warehouse, and existing functionality remain unchanged.

#!/usr/bin/env bash
# Scheduler-friendly entry point. Supply DB credentials through injected env only.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -z "${FOODFLOW_ETL_DATABASE_URL:-}" ]]; then
  echo 'FOODFLOW_ETL_DATABASE_URL must be injected by the scheduler or environment.' >&2
  exit 2
fi
exec "${FOODFLOW_PYTHON:-.venv-api/bin/python}" -m src.warehouse.cli run --raw "${FOODFLOW_RAW_DIR:-data/raw}"

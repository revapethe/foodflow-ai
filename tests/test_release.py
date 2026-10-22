"""Release evidence must fail closed when dates, metrics, or dependencies drift."""
from copy import deepcopy
from datetime import date, timedelta
import importlib.metadata

from fastapi.testclient import TestClient
import pytest

from api.main import app
from scripts.check_release import check_metrics
from scripts.check_dependencies import check
from src.intelligence.models import evaluate


def test_release_metadata_does_not_require_database_and_reports_revision(monkeypatch):
    monkeypatch.setenv('FOODFLOW_DATABASE_URL', 'unusable-connection-no-network-needed')
    monkeypatch.delenv('RENDER_GIT_COMMIT', raising=False)
    monkeypatch.delenv('FOODFLOW_RELEASE_REVISION', raising=False)
    with TestClient(app) as client:
        result = client.get('/version').json()
        assert result['release_revision'] == 'unknown'
        assert 'bounded_sql_assistant' in result['capabilities']
        monkeypatch.setenv('FOODFLOW_RELEASE_REVISION', 'reviewed-image')
        assert client.get('/version').json()['release_revision'] == 'reviewed-image'
        monkeypatch.setenv('RENDER_GIT_COMMIT', 'render-commit')
        assert client.get('/version').json()['release_revision'] == 'render-commit'


@pytest.fixture
def evidence():
    return evaluate([10+(i%7) for i in range(365)], [date(2025,1,1)+timedelta(days=i) for i in range(365)])


def test_release_recomputes_known_holdout(evidence):
    assert check_metrics(evidence) == {'mae':0, 'rmse':0, 'wape_percent':0}


@pytest.mark.parametrize('tamper', ['metric', 'coverage', 'leakage', 'missing_day', 'horizon', 'nan'])
def test_invalid_evidence_blocks_release(evidence, tamper):
    result = deepcopy(evidence)
    if tamper == 'metric':
        result['evaluation']['candidates'][result['selected_model']]['test']['mae'] = 100
    elif tamper == 'coverage':
        result['evaluation']['test_band_coverage_percent'] = 0
    elif tamper == 'leakage':
        result['evaluation']['folds'][0]['train_end'] = '2099-01-01'
    elif tamper == 'missing_day':
        result['evaluation']['heldout'][0]['date'] = result['evaluation']['heldout'][1]['date']
    elif tamper == 'horizon':
        result['predictions'][1]['date'] = result['predictions'][0]['date']
    else:
        result['evaluation']['heldout'][0]['actual'] = float('nan')
    with pytest.raises(ValueError):
        check_metrics(result)


def test_dependency_lock_rejects_drift_and_unpinned_entries(tmp_path, monkeypatch):
    class Distribution:
        metadata = {'Name':'example-package'}
        version = '1.0'
    monkeypatch.setattr(importlib.metadata, 'distributions', lambda: [Distribution()])
    lock = tmp_path/'runtime.lock'
    lock.write_text('example_package==1.0\n')
    check(lock)
    for content in ['example-package==2.0\n', 'other==1.0\n', 'example-package>=1.0\n']:
        lock.write_text(content)
        with pytest.raises(ValueError):
            check(lock)

"""Exercise the HTTP contract against an independently generated warehouse."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.generate_data import generate
from src.pipeline import build


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    raw, db = tmp_path / 'raw', tmp_path / 'warehouse.db'
    generate(120, 42, raw)
    build(raw, db)
    monkeypatch.setenv('FOODFLOW_DB_PATH', str(db))
    return db


def test_kpis_reconcile_with_database(warehouse):
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        response = client.get('/analytics')
    assert response.status_code == 200
    data = response.json()
    with sqlite3.connect(warehouse) as db:
        orders, revenue = db.execute("SELECT COUNT(*), ROUND(SUM(order_total),2) FROM fact_orders WHERE status='delivered'").fetchone()
    assert data['kpis']['all_orders'] == 120
    assert data['kpis']['delivered_orders'] == orders
    assert data['kpis']['revenue'] == revenue
    assert sum(d['orders'] for d in data['daily']) == 120
    assert round(sum(d['revenue'] for d in data['daily']), 2) == revenue
    assert sum(s['orders'] for s in data['statuses']) == 120
    assert data['forecast']['status'] == 'not_available'


def test_filters_apply_to_every_panel(warehouse):
    with sqlite3.connect(warehouse) as db:
        day, city = db.execute("SELECT o.order_date,r.city FROM fact_orders o JOIN dim_restaurant r USING(restaurant_key) WHERE o.status='delivered' LIMIT 1").fetchone()
        total, revenue = db.execute("SELECT COUNT(*), ROUND(SUM(CASE WHEN o.status='delivered' THEN o.order_total ELSE 0 END),2) FROM fact_orders o JOIN dim_restaurant r USING(restaurant_key) WHERE r.city=? AND o.order_date=?", (city, day)).fetchone()
        units = db.execute("SELECT SUM(i.quantity) FROM fact_order_items i JOIN fact_orders o USING(order_id) JOIN dim_restaurant r ON r.restaurant_key=o.restaurant_key WHERE r.city=? AND o.order_date=? AND o.status='delivered'", (city, day)).fetchone()[0]
    with TestClient(app) as client:
        data = client.get('/analytics', params={'city': city, 'start': day, 'end': day}).json()
    assert data['kpis']['all_orders'] == total
    assert data['kpis']['revenue'] == revenue
    assert {d['date'] for d in data['daily']} == {day}
    assert all(r['city'] == city for r in data['restaurants'])
    assert sum(p['units'] for p in data['products']) == units


def test_empty_and_injection_are_safe(warehouse):
    before = warehouse.read_bytes()
    with TestClient(app) as client:
        for params in [{'city': "'; DROP TABLE fact_orders;--"}, {'start': '2099-01-01'}]:
            response = client.get('/analytics', params=params)
            assert response.status_code == 200
            data = response.json()
            assert data['kpis']['revenue'] == 0
            assert data['kpis']['fulfillment_rate'] is None
            assert data['daily'] == data['products'] == data['restaurants'] == []
    assert warehouse.read_bytes() == before


def test_invalid_dates(warehouse):
    with TestClient(app) as client:
        assert client.get('/analytics?start=2025-12-01&end=2025-01-01').status_code == 422
        assert client.get('/analytics?start=invalid').status_code == 422


def test_missing_warehouse_is_actionable(tmp_path, monkeypatch):
    missing = tmp_path / 'missing.db'
    monkeypatch.setenv('FOODFLOW_DB_PATH', str(missing))
    with TestClient(app) as client:
        response = client.get('/analytics')
    assert response.status_code == 503
    assert 'src.pipeline build' in response.json()['detail']
    assert not missing.exists()


def test_overlapping_requests_keep_independent_connections(warehouse):
    from concurrent.futures import ThreadPoolExecutor
    with TestClient(app) as client:
        def request(i):
            params = {'city': 'Denver'} if i % 2 else {}
            response = client.get('/analytics', params=params)
            assert response.status_code == 200
            return params, response.json()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, range(32)))
    for params, data in results:
        assert data['filters']['city'] == params.get('city')
        assert sum(d['orders'] for d in data['daily']) == data['kpis']['all_orders']
        if params:
            assert all(r['city'] == 'Denver' for r in data['restaurants'])
        else:
            assert data['kpis']['all_orders'] == 120


def test_connection_survives_worker_handoff(warehouse):
    # FastAPI independently schedules sync dependency entry and endpoint work.
    from concurrent.futures import ThreadPoolExecutor
    from api.main import connection
    resource = connection()
    with ThreadPoolExecutor(max_workers=1) as pool:
        db = pool.submit(next, resource).result()
        try:
            assert db.execute('SELECT COUNT(*) FROM fact_orders').fetchone()[0] == 120
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                db.execute('DELETE FROM fact_orders')
        finally:
            resource.close()

"""Real PostgreSQL integration tests, each in a new disposable test database.

Set FOODFLOW_TEST_POSTGRES_URL to a development admin connection. Never uses or
clears the configured ETL warehouse; only generated ff_test_* databases are dropped.
"""
import csv
import os
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

psycopg = pytest.importorskip('psycopg')
from psycopg import sql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient

from api.main import app
from api.database import PostgresConnection, WarehouseUnavailable
from src.generate_data import generate
from src.pipeline import build
from src.warehouse.postgres import LOCK_ID, RunBusy, RunFailed, locked_connection, migrate, run
from src.warehouse.source import QualityError, load_snapshot


@pytest.fixture
def pg(tmp_path):
    admin = os.getenv('FOODFLOW_TEST_POSTGRES_URL')
    if not admin:
        pytest.skip('Set FOODFLOW_TEST_POSTGRES_URL for real PostgreSQL integration tests')
    name = 'ff_test_' + uuid.uuid4().hex
    reader = 'ff_reader_' + uuid.uuid4().hex
    with psycopg.connect(admin,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(reader)))
    dsn = make_conninfo(admin,dbname=name)
    raw = tmp_path / 'raw'
    generate(120,42,raw)
    try:
        yield dsn,raw,make_conninfo(dsn,user=reader)
    finally:
        with psycopg.connect(admin,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(reader)))


def read(raw,table):
    with (raw/f'{table}.csv').open() as f:
        return list(csv.DictReader(f))


def write(raw,table,rows):
    with (raw/f'{table}.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def scalar(dsn,query,params=()):
    with psycopg.connect(dsn) as conn:
        return conn.execute(query,params).fetchone()[0]


def test_initial_load_and_unchanged_rerun(pg):
    dsn,raw,_ = pg
    snapshot,_=load_snapshot(raw)
    first=run(dsn,raw)
    second=run(dsn,raw)
    for table,rows in snapshot.items():
        assert first['counts'][table]['inserted']==len(rows)
        assert second['counts'][table]=={'scanned':len(rows),'inserted':0,'updated':0,'unchanged':len(rows)}
    assert all(v['changed']==0 for v in second['counts']['models'].values())
    assert scalar(dsn,'SELECT COUNT(DISTINCT _run_id) FROM foodflow_analytics.fact_orders')==1
    assert scalar(dsn,"SELECT COUNT(*) FROM foodflow_ops.runs WHERE status='SUCCESS'")==2


def test_late_arrival_and_correction_are_incremental(pg):
    dsn,raw,_=pg
    run(dsn,raw)
    orders,items=read(raw,'orders'),read(raw,'order_items')
    original=next(o for o in orders if o['status']=='delivered')
    new=dict(original,order_id=str(max(int(o['order_id']) for o in orders)+1),ordered_at='2024-01-01T12:00:00')
    next_id=max(int(i['order_item_id']) for i in items)+1
    additions=[dict(i,order_item_id=str(next_id+n),order_id=new['order_id']) for n,i in enumerate([i for i in items if i['order_id']==original['order_id']])]
    write(raw,'orders',orders+[new]);write(raw,'order_items',items+additions)
    added=run(dsn,raw)
    assert added['counts']['orders']['inserted']==1
    assert added['counts']['order_items']['inserted']==len(additions)
    assert scalar(dsn,'SELECT MIN(order_date)::text FROM foodflow_analytics.fact_orders')=='2024-01-01'
    orders=read(raw,'orders')
    orders[0]['delivery_fee']=str(Decimal(orders[0]['delivery_fee'])+1)
    orders[0]['order_total']=str(Decimal(orders[0]['order_total'])+1)
    write(raw,'orders',orders)
    fixed=run(dsn,raw)
    assert fixed['counts']['orders']['inserted']==0
    assert fixed['counts']['orders']['updated']==1
    assert fixed['counts']['models']['fact_orders']['changed']==1
    assert scalar(dsn,'SELECT COUNT(*) FROM foodflow_analytics.fact_orders')==121
    again=run(dsn,raw)
    assert all(v['changed']==0 for v in again['counts']['models'].values())


def test_dimension_and_menu_corrections_propagate(pg):
    dsn,raw,_=pg
    run(dsn,raw)
    restaurants,menus=read(raw,'restaurant'),read(raw,'menu')
    restaurants[0]['restaurant_name']='Corrected restaurant name'
    target=menus[0]['menu_id']
    expected=sum(i['menu_id']==target for i in read(raw,'order_items'))
    menus[0]['food_id']='12' if menus[0]['food_id']!='12' else '1'
    write(raw,'restaurant',restaurants);write(raw,'menu',menus)
    result=run(dsn,raw)
    assert result['counts']['restaurant']['updated']==1
    assert result['counts']['models']['dim_restaurant']['changed']==1
    assert result['counts']['models']['fact_order_items']['changed']==expected
    assert scalar(dsn,'SELECT restaurant_name FROM foodflow_analytics.dim_restaurant WHERE restaurant_key=1')=='Corrected restaurant name'
    assert scalar(dsn,'SELECT COUNT(*) FROM foodflow_analytics.fact_order_items WHERE food_key=12 AND order_item_id IN (SELECT order_item_id FROM foodflow_raw.order_items WHERE menu_id=1)')==expected


def test_invalid_source_is_logged_and_last_publication_survives(pg):
    dsn,raw,_=pg
    first=run(dsn,raw)
    orders=read(raw,'orders');orders[0]['order_total']='99999.99';write(raw,'orders',orders)
    with pytest.raises(RunFailed) as error:
        run(dsn,raw)
    assert error.value.code=='QUALITY_REJECTED'
    assert len(scalar(dsn,'SELECT source_manifest FROM foodflow_ops.runs WHERE run_id=%s',(error.value.run_id,)))==7
    assert scalar(dsn,'SELECT status FROM foodflow_ops.runs WHERE run_id=%s',(error.value.run_id,))=='FAILED'
    assert str(scalar(dsn,'SELECT _run_id FROM foodflow_analytics.fact_orders LIMIT 1'))==first['run_id']


def test_failure_after_upsert_rolls_back_and_retry_recovers(pg):
    dsn,raw,_=pg
    first=run(dsn,raw)
    restaurants=read(raw,'restaurant');restaurants[0]['restaurant_name']='Retry correction';write(raw,'restaurant',restaurants)
    with patch('src.warehouse.postgres.validate_warehouse',side_effect=QualityError('injected publication check failure')):
        with pytest.raises(RunFailed):
            run(dsn,raw)
    assert str(scalar(dsn,'SELECT _run_id FROM foodflow_raw.restaurant WHERE restaurant_id=1'))==first['run_id']
    failed=scalar(dsn,"SELECT row_counts FROM foodflow_ops.runs WHERE status='FAILED'")
    assert failed['committed'] is False and failed['attempted']['restaurant']['updated']==1
    recovered=run(dsn,raw)
    assert recovered['counts']['restaurant']['updated']==1
    assert scalar(dsn,'SELECT restaurant_name FROM foodflow_analytics.dim_restaurant WHERE restaurant_key=1')=='Retry correction'
    assert scalar(dsn,"SELECT COUNT(*) FROM foodflow_ops.runs WHERE status='FAILED'")==1


def test_missing_keys_do_not_silently_delete_history(pg):
    dsn,raw,_=pg
    first=run(dsn,raw)
    reviews=read(raw,'reviews');write(raw,'reviews',reviews[:-1])
    with pytest.raises(RunFailed,match='snapshot omits'):
        run(dsn,raw)
    assert scalar(dsn,'SELECT COUNT(*) FROM foodflow_raw.reviews')==len(reviews)
    assert str(scalar(dsn,'SELECT _run_id FROM foodflow_raw.reviews LIMIT 1'))==first['run_id']


def test_single_writer_lock_and_interrupted_run_recovery(pg):
    dsn,raw,_=pg
    run(dsn,raw)
    with psycopg.connect(dsn,autocommit=True) as lock:
        lock.execute('SELECT pg_advisory_lock(%s)',(LOCK_ID,))
        with pytest.raises(RunBusy):run(dsn,raw)
        assert scalar(dsn,'SELECT COUNT(*) FROM foodflow_analytics.fact_orders')==120
    abandoned=uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute("INSERT INTO foodflow_ops.runs(run_id,status) VALUES(%s,'RUNNING')",(abandoned,))
    run(dsn,raw)
    assert scalar(dsn,'SELECT status FROM foodflow_ops.runs WHERE run_id=%s',(abandoned,))=='ABANDONED'


def test_postgres_api_matches_sqlite_and_reader_cannot_write(pg,tmp_path,monkeypatch):
    dsn,raw,reader_dsn=pg
    run(dsn,raw)
    role=psycopg.conninfo.conninfo_to_dict(reader_dsn)['user']
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA foodflow_analytics TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA foodflow_analytics TO {}').format(sql.Identifier(role)))
    db=tmp_path/'sqlite.db';build(raw,db)
    monkeypatch.delenv('FOODFLOW_DATABASE_URL',raising=False)
    monkeypatch.setenv('FOODFLOW_DB_PATH',str(db))
    cases=[{}, {'city':'Denver'},{'city':'Denver','start':'2025-03-01','end':'2025-06-30'}, {'start':'2099-01-01'}, {'city':"'; DROP TABLE fact_orders;--"}]
    with TestClient(app) as client:
        expected=[client.get('/analytics',params=p).json() for p in cases]
        from api.assistant import EXAMPLES
        assistant_expected=[client.post('/assistant',json={'question':q}).json() for q in EXAMPLES]

    monkeypatch.setenv('FOODFLOW_DATABASE_URL',reader_dsn)
    with TestClient(app) as client:
        assert client.get('/health').json()=={'status':'ok'}
        for params,reference in zip(cases,expected):
            response=client.get('/analytics',params=params)
            assert response.status_code==200,response.text
            actual=response.json()
            assert 'PostgreSQL' in actual.pop('source')
            reference.pop('source')
            assert actual==reference
        assert client.get('/analytics?start=bad').status_code==422
        for question,reference in zip(EXAMPLES,assistant_expected):
            response=client.post('/assistant',json={'question':question})
            assert response.status_code==200,response.text
            actual=response.json()
            assert actual['status']=='answered'
            actual.pop('queried_at'); reference.pop('queried_at')
            assert actual==reference

    reader=PostgresConnection(reader_dsn)
    try:
        with pytest.raises(WarehouseUnavailable):reader.execute('DELETE FROM fact_orders')
        with pytest.raises(WarehouseUnavailable):reader.execute('SELECT * FROM foodflow_raw.users')
    finally:reader.close()
    # Role grants independently forbid writes, even outside API read-only mode.
    with psycopg.connect(reader_dsn,autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):conn.execute('DELETE FROM foodflow_analytics.fact_orders')


@pytest.mark.parametrize('table,column,value',[
    ('orders','ordered_at','not-a-date'), ('orders','delivery_fee','NaN'),
    ('users','user_name',''), ('orders','user_id','99999'),
    ('reviews','rating','6'), ('order_items','quantity','0'),
])
def test_source_contract_rejects_invalid_data(tmp_path,table,column,value):
    raw=tmp_path/'raw';generate(30,42,raw)
    rows=read(raw,table);rows[0][column]=value;write(raw,table,rows)
    with pytest.raises(QualityError):load_snapshot(raw)


def test_api_snapshot_stays_consistent_during_publication(pg,monkeypatch):
    dsn,raw,_=pg
    run(dsn,raw)
    previous=scalar(dsn,"SELECT COUNT(*) FROM foodflow_analytics.fact_orders WHERE status='delivered'")
    orders=read(raw,'orders')
    next(o for o in orders if o['status']=='delivered')['status']='cancelled'
    write(raw,'orders',orders)
    monkeypatch.setenv('FOODFLOW_DATABASE_URL',dsn)
    execute=PostgresConnection.execute
    published=[]
    def publish_between_panels(self,query,params=()):
        result=execute(self,query,params)
        if 'AS all_orders' in query and not published:
            published.append(run(dsn,raw))
        return result
    monkeypatch.setattr(PostgresConnection,'execute',publish_between_panels)
    with TestClient(app) as client:
        first=client.get('/analytics')
        assert first.status_code==200,first.text
        data=first.json()
        assert data['kpis']['delivered_orders']==previous
        assert sum(d['delivered_orders'] for d in data['daily'])==previous
        assert round(sum(d['revenue'] for d in data['daily']),2)==data['kpis']['revenue']
        assert client.get('/analytics').json()['kpis']['delivered_orders']==previous-1
    assert published[0]['counts']['models']['fact_orders']['changed']==1


def test_duplicate_keys_and_schema_drift_are_rejected(tmp_path):
    raw=tmp_path/'raw';generate(30,42,raw)
    users=read(raw,'users');users[1]['user_id']=users[0]['user_id'];write(raw,'users',users)
    with pytest.raises(QualityError,match='duplicate primary key'):load_snapshot(raw)
    users[1]['user_id']='2';write(raw,'users',users)
    path=raw/'orders.csv'
    path.write_text(path.read_text().replace('order_total','unexpected_total',1))
    with pytest.raises(QualityError,match='schema mismatch'):load_snapshot(raw)


def test_schema_only_database_is_not_reported_ready(pg,monkeypatch):
    dsn,_,_=pg
    with locked_connection(dsn) as conn:migrate(conn)
    monkeypatch.setenv('FOODFLOW_DATABASE_URL',dsn)
    with TestClient(app) as client:
        for endpoint in ('/health','/analytics'):
            response=client.get(endpoint)
            assert response.status_code==503
            assert 'no published orders' in response.json()['detail']

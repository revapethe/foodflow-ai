"""Forecast leakage guards, numerical evaluation, anomaly causality and HTTP freshness."""
import json
from datetime import date,timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.intelligence.anomalies import detect
from src.intelligence.data import snapshot,warehouse
from src.intelligence.models import evaluate,features,fit_state,metrics,predict_state
from src.intelligence.train import atomic_json,build_artifact,market_series
from src.generate_data import generate
from src.pipeline import build


def calendar(n=365):return [date(2025,1,1)+timedelta(days=i) for i in range(n)]


def test_seasonal_baseline_and_chronological_partitions():
    days=calendar(); y=[10+(i%7)*2 for i in range(365)]
    result=evaluate(y,days)
    assert result['selected_model']=='seasonal_naive'
    assert result['evaluation']['candidates']['seasonal_naive']['test']['mae']==0
    folds=result['evaluation']['folds']
    assert len(folds)==3
    assert all(f['train_end']<f['validation_start']<=f['validation_end'] for f in folds)
    assert folds[-1]['validation_end']<result['evaluation']['calibration_start']
    assert result['evaluation']['calibration_end']<result['evaluation']['test_start']
    assert len(result['predictions'])==14
    assert result['predictions'][0]['date']=='2026-01-01'
    assert all(p['prediction']==y[(365+i)%7] for i,p in enumerate(result['predictions']))


def test_final_holdout_cannot_change_selection_or_test_predictions():
    y=np.random.default_rng(42).poisson(8,365).tolist()
    original=evaluate(y,calendar())
    changed=evaluate(y[:-28]+[10000]*28,calendar())
    assert original['selected_model']==changed['selected_model']
    assert original['evaluation']['error_band_width']==changed['evaluation']['error_band_width']
    for name,result in original['evaluation']['candidates'].items():
        assert result['validation']==changed['evaluation']['candidates'][name]['validation']
    assert [p['prediction'] for p in original['evaluation']['heldout']]==[p['prediction'] for p in changed['evaluation']['heldout']]
    assert original['evaluation']['candidates'][original['selected_model']]['test']!=changed['evaluation']['candidates'][changed['selected_model']]['test']


def test_stored_ridge_state_reproduces_forecast_without_future_targets():
    days=calendar(); y=(20+np.sin(np.arange(365)*2*np.pi/7)*5).tolist()
    state=fit_state('ridge_autoregression',y,days)
    output=predict_state(state,y,days,14)
    serialized=json.loads(json.dumps(state))
    assert np.allclose(output,predict_state(serialized,y,days,14))
    assert len(state['coef'])==len(state['features'])==10
    assert all(v>=0 and np.isfinite(v) for v in output)
    assert features(y[:28],days[28],28)[0]==y[27]


def test_reported_metrics_are_recomputed_from_actual_holdout():
    result=evaluate(np.random.default_rng(7).poisson(5,365),calendar())
    points=result['evaluation']['heldout']
    expected=metrics([p['actual'] for p in points],[p['prediction'] for p in points])
    actual=result['evaluation']['candidates'][result['selected_model']]['test']
    assert expected==pytest.approx(actual,abs=1e-6)
    coverage=sum(p['lower']<=p['actual']<=p['upper'] for p in points)/len(points)*100
    assert coverage==pytest.approx(result['evaluation']['test_band_coverage_percent'],abs=1e-6)
    assert all(0<=p['lower']<=p['prediction']<=p['upper'] for p in result['predictions'])
    assert metrics([0,0],[1,2])['wape_percent'] is None


def test_insufficient_and_invalid_history():
    assert evaluate([1]*100,calendar(100))['status']=='insufficient_history'
    assert evaluate([0]*365,calendar())['status']=='insufficient_history'
    with pytest.raises(ValueError):evaluate([float('nan')]*365,calendar())
    with pytest.raises(ValueError):evaluate([1]*364,calendar())


def test_anomaly_detector_is_past_only_and_handles_zero_variance():
    days=calendar(); values=[100.]*365;values[80]=1000;values[130]=0
    original=detect(days,values,'orders')
    assert {(f['date'],f['direction']) for f in original}=={(days[80].isoformat(),'high'),(days[130].isoformat(),'low')}
    changed=detect(days,values[:200]+[10000.]*165,'orders')
    assert [f for f in changed if f['date']<days[200].isoformat()]==[f for f in original if f['date']<days[200].isoformat()]
    assert detect(days,[None]*365,'delivery_minutes')==[]
    assert detect(days,[0]*365,'orders')==[]


@pytest.fixture
def model_warehouse(tmp_path,monkeypatch):
    monkeypatch.delenv('FOODFLOW_DATABASE_URL',raising=False)
    raw=tmp_path/'raw';db=tmp_path/'warehouse.db'
    generate(600,42,raw);build(raw,db)
    monkeypatch.setenv('FOODFLOW_DB_PATH',str(db))
    target=tmp_path/'intelligence.json';monkeypatch.setenv('FOODFLOW_INTELLIGENCE_PATH',str(target))
    with warehouse() as connection:rows,fingerprint=snapshot(connection)
    artifact=build_artifact(rows,fingerprint);atomic_json(target,artifact)
    return raw,db,target,artifact


def test_api_serves_matching_warehouse_and_date_filters_only_anomalies(model_warehouse):
    _,_,_,artifact=model_warehouse
    with TestClient(app) as client:
        all_data=client.get('/intelligence').json()
        assert all_data['status']=='ready'
        assert all_data['source']['orders']==600
        assert all_data['input_fingerprint']==artifact['input_fingerprint']
        city=client.get('/intelligence?city=Denver').json()
        filtered=client.get('/intelligence?city=Denver&start=2025-03-01&end=2025-06-30').json()
        assert city['predictions']==filtered['predictions']
        assert all('2025-03-01'<=f['date']<='2025-06-30' for f in filtered['anomalies']['flags'])
        assert 'Full market history' in filtered['forecast_scope']
        assert client.get('/intelligence?start=2025-10-01&end=2025-01-01').status_code==422
        assert client.get('/intelligence?city=Unknown').json()['status']=='not_available'
        assert 'model_state' not in all_data


def test_stale_artifact_is_not_served_after_warehouse_changes(model_warehouse):
    raw,db,_,_=model_warehouse
    import pandas as pd
    frame=pd.read_csv(raw/'orders.csv');frame.loc[0,'status']='cancelled' if frame.loc[0,'status']=='delivered' else 'delivered'
    # Change financial input while preserving counts: daily delivered revenue is
    # also an anomaly input and must invalidate the artifact.
    frame.loc[0,'delivery_fee']+=1;frame.loc[0,'order_total']+=1
    frame.to_csv(raw/'orders.csv',index=False);build(raw,db)
    with TestClient(app) as client:
        response=client.get('/intelligence')
        assert response.status_code==200
        assert response.json()['status']=='stale'
        assert 'predictions' not in response.json()
        assert client.get('/analytics').status_code==200


def test_missing_or_invalid_artifact_preserves_historical_dashboard(model_warehouse):
    _,_,target,_=model_warehouse
    for content in ('invalid json','{"version": 999, "markets": {}}'):
        target.write_text(content)
        with TestClient(app) as client:
            assert client.get('/intelligence').json()['status']=='not_available'
            assert client.get('/analytics').status_code==200
    target.unlink()
    with TestClient(app) as client:
        assert client.get('/intelligence').json()['status']=='not_available'


def test_calendar_zero_fill_and_delivery_weighting_are_explicit():
    rows=[{'date':'2025-01-01','city':'A','orders':2,'revenue':20,'delivered_orders':2,'duration_observations':1,'delivery_minutes':10},
          {'date':'2025-01-03','city':'A','orders':1,'revenue':30,'delivered_orders':1,'duration_observations':1,'delivery_minutes':30}]
    days,values=market_series(rows)
    assert len(days)==3
    assert values['orders']==[2,0,1]
    assert values['delivery_minutes']==[10,None,30]


def test_new_operational_kpis_match_warehouse(model_warehouse):
    _,db,_,_=model_warehouse
    import sqlite3
    with sqlite3.connect(db) as connection:
        cancelled=connection.execute("SELECT COUNT(*) FROM fact_orders WHERE status='cancelled'").fetchone()[0]
        slow=connection.execute("SELECT COUNT(*) FROM fact_orders WHERE status='delivered' AND delivery_minutes>60").fetchone()[0]
        units=connection.execute("SELECT SUM(i.quantity) FROM fact_order_items i JOIN fact_orders o USING(order_id) WHERE o.status='delivered'").fetchone()[0]
    with TestClient(app) as client:k=client.get('/analytics').json()['kpis']
    assert k['cancelled_orders']==cancelled and k['over_60_min_orders']==slow and k['units_sold']==units
    assert k['units_per_delivered_order']==round(units/k['delivered_orders'],2)

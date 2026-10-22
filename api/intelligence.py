"""Serve materialized, evaluated forecasts only when warehouse inputs match."""
import json
import os
from functools import lru_cache
from pathlib import Path

from src.config import ROOT
from src.intelligence.data import VERSION,snapshot


@lru_cache(maxsize=4)
def read_artifact(path,mtime,size):
    if size>20_000_000:raise ValueError('Artifact exceeds size limit')
    with open(path,encoding='utf-8') as file:
        def invalid_constant(_):raise ValueError('Non-finite artifact value')
        value=json.load(file,parse_constant=invalid_constant)
    if not isinstance(value,dict) or value.get('version')!=VERSION or not isinstance(value.get('markets'),dict):
        raise ValueError('Unsupported artifact format')
    required={'as_of','selected_model','selected_label','evaluation','predictions','history','horizon_days','anomalies'}
    for market in value['markets'].values():
        if not isinstance(market,dict) or 'status' not in market or 'anomalies' not in market:
            raise ValueError('Invalid market artifact')
        if market['status']=='ready' and not required.issubset(market):
            raise ValueError('Incomplete market artifact')
        if not isinstance(market['anomalies'],dict) or not isinstance(market['anomalies'].get('flags'),list):
            raise ValueError('Invalid anomaly artifact')
    return value


def insights(db,city=None,start=None,end=None):
    path=Path(os.getenv('FOODFLOW_INTELLIGENCE_PATH',str(ROOT/'artifacts/intelligence.json')))
    try:
        stat=path.stat()
        artifact=read_artifact(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
    except (OSError,ValueError,UnicodeError):
        return {'status':'not_available','reason':'Evaluated intelligence is unavailable. Run python -m src.intelligence.train.'}
    _,fingerprint=snapshot(db)
    if fingerprint!=artifact.get('input_fingerprint'):
        return {'status':'stale','reason':'Warehouse inputs have changed. Retrain intelligence before using forecasts or anomaly flags.'}
    key=city if city is not None else '__all__'
    if key not in artifact['markets']:
        return {'status':'not_available','reason':'No evaluated model exists for this market.'}
    source=artifact['markets'][key]
    result={k:v for k,v in source.items() if k!='model_state'}
    flags=source['anomalies']['flags']
    filtered=[flag for flag in flags if (start is None or flag['date']>=str(start)) and (end is None or flag['date']<=str(end))]
    result['anomalies']={**source['anomalies'],'flags':filtered,'total_before_date_filter':len(flags)}
    return {**result,'market':city or 'All cities','source':artifact['source'],'trained_at':artifact['trained_at'],
        'input_fingerprint':fingerprint,'forecast_scope':'Full market history through the dataset as_of date. Date filters apply to anomaly flags and historical KPIs only.'}

"""Offline training and evaluation from a read-only warehouse snapshot. No API keys."""
import argparse
import json
import os
import platform
import tempfile
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

import numpy as np
import sklearn

from src.config import ROOT
from .anomalies import detect
from .data import VERSION,snapshot,warehouse
from .models import evaluate


def market_series(rows, city=None):
    start,end=date.fromisoformat(rows[0]['date']),date.fromisoformat(rows[-1]['date'])
    days=[start+timedelta(days=i) for i in range((end-start).days+1)]
    grouped={d.isoformat():{'orders':0,'revenue':0.,'delivered':0,'duration_sum':0.} for d in days}
    for row in rows:
        if city is not None and row['city']!=city:
            continue
        item=grouped[row['date']]
        item['orders']+=row['orders'];item['revenue']+=row['revenue']
        if row['delivery_minutes'] is not None:
            item['delivered']+=row['duration_observations']
            item['duration_sum']+=row['delivery_minutes']*row['duration_observations']
    return days, {'orders':[grouped[d.isoformat()]['orders'] for d in days],
        'revenue':[round(grouped[d.isoformat()]['revenue'],2) for d in days],
        'delivery_minutes':[round(grouped[d.isoformat()]['duration_sum']/grouped[d.isoformat()]['delivered'],6) if grouped[d.isoformat()]['delivered'] else None for d in days]}


def build_artifact(rows,fingerprint):
    if not rows:
        raise ValueError('No orders in warehouse; run ETL before training')
    markets={}
    for city in [None,*sorted({r['city'] for r in rows})]:
        days,series=market_series(rows,city)
        result=evaluate(series['orders'],days)
        flags=[flag for metric,values in series.items() for flag in detect(days,values,metric)]
        result['anomalies']={'method':'Past-only weekday median and MAD with scale floors',
            'threshold':3.5,'lookback_days':56,'minimum_prior_observations':28,
            'flags':sorted(flags,key=lambda r:(-abs(r['score']),r['date'],r['metric'])),
            'evaluation':'No labeled incidents are available; precision, recall, and business impact are not established.'}
        markets[city if city is not None else '__all__']=result
    return {'version':VERSION,'input_fingerprint':fingerprint,'trained_at':datetime.now(timezone.utc).isoformat(),
        'source':{'start':rows[0]['date'],'end':rows[-1]['date'],'orders':sum(r['orders'] for r in rows),'synthetic':True},
        'packages':{'python':platform.python_version(),'numpy':np.__version__,'scikit_learn':sklearn.__version__},'markets':markets}


def atomic_json(path,content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False,encoding='utf-8') as f:
            temporary=f.name
            json.dump(content,f,indent=2,sort_keys=True,allow_nan=False)
            f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        if temporary and Path(temporary).exists():Path(temporary).unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/intelligence.json')
    parser.add_argument('--report',type=Path,help='Optional reproducible evaluation evidence to save for review')
    args=parser.parse_args()
    with warehouse() as db:
        rows,fingerprint=snapshot(db)
    artifact=build_artifact(rows,fingerprint)
    atomic_json(args.output,artifact)
    report={k:artifact[k] for k in ('version','input_fingerprint','trained_at','source','packages')}
    report['markets']={city:{k:v for k,v in result.items() if k not in ('model_state','history','predictions')} for city,result in artifact['markets'].items()}
    if args.report:atomic_json(args.report,report)
    print(json.dumps({'status':'trained','output':str(args.output),'source':artifact['source'],
        'markets':{city:{'status':r['status'],'selected':r.get('selected_model'),'test':r.get('evaluation',{}).get('candidates',{}).get(r.get('selected_model'),{}).get('test'), 'anomaly_flags':len(r['anomalies']['flags'])} for city,r in artifact['markets'].items()}},sort_keys=True))


if __name__=='__main__':main()

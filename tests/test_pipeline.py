import sqlite3
import pandas as pd
import pytest
from src.generate_data import generate
from src.pipeline import build,load_frames
from src.quality import validate

def test_end_to_end(tmp_path):
    raw=tmp_path/'raw';db=tmp_path/'foodflow.db'
    counts=generate(120,42,raw)
    assert len(counts)==7 and counts['orders']==120
    result=build(raw,db)
    assert result['quality']['status']=='PASS'
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT COUNT(*) FROM fact_orders').fetchone()[0]==120
        assert con.execute('SELECT COUNT(*) FROM fact_order_items').fetchone()[0]>=120
        assert con.execute('SELECT COUNT(*) FROM mart_daily_sales').fetchone()[0]>0

def test_reject_orphan_foreign_key(tmp_path):
    raw=tmp_path/'raw';generate(20,42,raw)
    frames=load_frames(raw)
    frames['orders'].loc[0,'user_id']=999999
    with pytest.raises(ValueError,match='Broken foreign key'): validate(frames)

def test_reject_bad_reconciliation(tmp_path):
    raw=tmp_path/'raw';generate(20,42,raw)
    frames=load_frames(raw)
    frames['orders'].loc[0,'order_total']+=10
    with pytest.raises(ValueError,match='reconciliation'): validate(frames)

def test_deterministic(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b'
    generate(20,42,a);generate(20,42,b)
    assert (a/'orders.csv').read_bytes()==(b/'orders.csv').read_bytes()

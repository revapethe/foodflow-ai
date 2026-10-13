"""CSV -> validated SQLite staging -> dimensional warehouse + marts."""
import argparse
import json
import sqlite3
import pandas as pd
from .config import RAW,DB,TABLES
from .generate_data import generate
from .quality import validate

def load_frames(raw=RAW):
    return {t:pd.read_csv(raw/f'{t}.csv') for t in TABLES}

def build(raw=RAW, db=DB):
    data=load_frames(raw)
    report=validate(data)
    db.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(db) as con:
        con.execute('PRAGMA foreign_keys = ON')
        for t in TABLES: data[t].to_sql('stg_'+t,con,if_exists='replace',index=False)
        script=(__import__('pathlib').Path(__file__).resolve().parents[1]/'sql'/'models.sql').read_text(encoding='utf-8')
        con.executescript(script)
        metrics={row[0]:row[1] for row in con.execute('SELECT metric,value FROM mart_kpis')}
    return {'quality':report,'metrics':metrics,'database':str(db)}

def main():
    parser=argparse.ArgumentParser(description='FoodFlow local ETL')
    parser.add_argument('action',choices=['generate','build','all'],nargs='?',default='all')
    parser.add_argument('--orders',type=int,default=3000)
    args=parser.parse_args()
    if args.action in ('generate','all'): print('Generated:',generate(n_orders=args.orders))
    if args.action in ('build','all'): print(json.dumps(build(),indent=2))
if __name__=='__main__': main()

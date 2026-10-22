"""python -m src.warehouse.cli {run,migrate,status,grant-reader}"""
import argparse
import json
import logging
import os
import sys

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from src.config import RAW
from .postgres import RunBusy, RunFailed, locked_connection, migrate, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','migrate','status','grant-reader'])
    parser.add_argument('--raw',default=str(RAW),help='Complete snapshot directory; original CSVs are never generated')
    parser.add_argument('--role',help='Existing read-only database role to grant analytics access')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    dsn = os.getenv('FOODFLOW_ETL_DATABASE_URL')
    if not dsn:
        parser.error('Set FOODFLOW_ETL_DATABASE_URL in the execution environment; do not pass credentials as CLI arguments')
    try:
        if args.action=='run':
            print(json.dumps(run(dsn,args.raw),sort_keys=True))
        elif args.action=='status':
            with psycopg.connect(dsn,row_factory=dict_row) as conn:
                rows=conn.execute('SELECT run_id,status,started_at,finished_at,duration_ms,quality_status,error_code,row_counts FROM foodflow_ops.runs ORDER BY started_at DESC LIMIT 20').fetchall()
                print(json.dumps(rows,default=str))
        else:
            with locked_connection(dsn) as conn:
                migrate(conn)
                if args.action=='grant-reader':
                    if not args.role:
                        parser.error('grant-reader requires --role for an existing role')
                    with conn.transaction():
                        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA foodflow_analytics TO {}').format(sql.Identifier(args.role)))
                        conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA foodflow_analytics TO {}').format(sql.Identifier(args.role)))
                        conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA foodflow_analytics GRANT SELECT ON TABLES TO {}').format(sql.Identifier(args.role)))
            print(json.dumps({'status':'OK','action':args.action}))
        return 0
    except RunBusy:
        print(json.dumps({'status':'BUSY','detail':'Another ETL writer is active'}),file=sys.stderr)
        return 75
    except RunFailed as exc:
        print(json.dumps({'status':'FAILED','run_id':exc.run_id,'error_code':exc.code,'detail':exc.detail}),file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(json.dumps({'status':'FAILED','error_code':exc.sqlstate or 'DATABASE_UNAVAILABLE','detail':'Check database connectivity, role permissions and migrations; credentials are never logged'}),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())

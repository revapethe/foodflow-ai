"""Atomic hash-based upserts with lineage, run history and single-writer locking."""
import hashlib
import json
import logging
import time
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .source import SPECS, QualityError, canonical, load_snapshot

LOCK_ID = 741906210
SCHEMA = Path(__file__).resolve().parents[2] / 'sql/postgres/001_warehouse.sql'
LOG = logging.getLogger('foodflow.etl')

MODELS = {
 'dim_customer': ('customer_key', ['customer_key','user_name','city','signup_date'], 'SELECT user_id,user_name,city,signup_date FROM foodflow_raw.users'),
 'dim_restaurant': ('restaurant_key', ['restaurant_key','restaurant_name','city','cuisine'], 'SELECT restaurant_id,restaurant_name,city,cuisine FROM foodflow_raw.restaurant'),
 'dim_food': ('food_key', ['food_key','food_name','category'], 'SELECT food_id,food_name,category FROM foodflow_raw.food'),
 'fact_orders': ('order_id', ['order_id','customer_key','restaurant_key','ordered_at','order_date','status','payment_method','delivery_minutes','delivery_fee','order_total'], 'SELECT order_id,user_id,restaurant_id,ordered_at,ordered_at::date,status,payment_method,delivery_minutes,delivery_fee,order_total FROM foodflow_raw.orders'),
 'fact_order_items': ('order_item_id', ['order_item_id','order_id','restaurant_key','food_key','quantity','unit_price','line_total'], 'SELECT i.order_item_id,i.order_id,m.restaurant_id,m.food_id,i.quantity,i.unit_price,i.line_total FROM foodflow_raw.order_items i JOIN foodflow_raw.menu m USING(menu_id)'),
 'fact_reviews': ('review_id', ['review_id','order_id','customer_key','restaurant_key','rating','review_text'], 'SELECT review_id,order_id,user_id,restaurant_id,rating,review_text FROM foodflow_raw.reviews'),
}


class RunBusy(RuntimeError):
    pass


class RunFailed(RuntimeError):
    def __init__(self, run_id, code, detail):
        self.run_id, self.code, self.detail = str(run_id), code, detail
        super().__init__(f'Run {run_id} failed: {detail}')


def event(name, **fields):
    LOG.info(json.dumps({'event': name, **fields}, default=str, sort_keys=True))


def migrate(conn):
    # Connection owner must take the pipeline advisory lock first.
    existing = conn.execute("SELECT to_regclass('foodflow_ops.schema_versions') AS name").fetchone()['name']
    if existing:
        version = conn.execute('SELECT MAX(version) AS version FROM foodflow_ops.schema_versions').fetchone()['version']
        if version == 1:
            return
        if version is not None:
            raise RuntimeError('Unsupported warehouse schema version')
    with conn.transaction():
        conn.execute(SCHEMA.read_text())


def locked_connection(dsn):
    conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=10)
    conn.execute("SET statement_timeout='60s'")
    conn.execute("SET lock_timeout='5s'")
    if not conn.execute('SELECT pg_try_advisory_lock(%s) AS acquired', (LOCK_ID,)).fetchone()['acquired']:
        conn.close()
        raise RunBusy('Another FoodFlow ETL run holds the writer lock')
    return conn


def raw_upsert(conn, table, rows, run_id):
    fields = [name for name,_ in SPECS[table]]
    key, temp = fields[0], f'incoming_{table}'
    conn.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE foodflow_raw.{} INCLUDING DEFAULTS) ON COMMIT DROP').format(sql.Identifier(temp), sql.Identifier(table)))
    columns = fields + ['_row_hash', '_run_id']
    with conn.cursor().copy(sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(temp), sql.SQL(',').join(map(sql.Identifier, columns)))) as copy:
        for row in rows:
            digest = hashlib.sha256(canonical(row).encode()).hexdigest()
            copy.write_row([row[c] for c in fields] + [digest, run_id])
    removed = conn.execute(sql.SQL('SELECT COUNT(*) AS n FROM foodflow_raw.{} r LEFT JOIN {} i USING({}) WHERE i.{} IS NULL').format(sql.Identifier(table), sql.Identifier(temp), sql.Identifier(key), sql.Identifier(key))).fetchone()['n']
    if removed:
        raise QualityError(f'{table}: snapshot omits {removed} existing keys; deletion requires an explicit future policy')
    counts = conn.execute(sql.SQL('''SELECT COUNT(*) FILTER(WHERE r.{key} IS NULL) AS inserted,
        COUNT(*) FILTER(WHERE r.{key} IS NOT NULL AND r._row_hash<>i._row_hash) AS updated,
        COUNT(*) FILTER(WHERE r._row_hash=i._row_hash) AS unchanged
        FROM {temp} i LEFT JOIN foodflow_raw.{table} r USING({key})''').format(key=sql.Identifier(key), temp=sql.Identifier(temp), table=sql.Identifier(table))).fetchone()
    updates = fields[1:] + ['_row_hash','_run_id','_loaded_at']
    all_columns = columns + ['_loaded_at']
    conn.execute(sql.SQL('''INSERT INTO foodflow_raw.{table} AS current ({columns})
        SELECT {columns} FROM {temp} WHERE true ON CONFLICT ({key}) DO UPDATE SET {updates}
        WHERE current._row_hash IS DISTINCT FROM EXCLUDED._row_hash''').format(
            table=sql.Identifier(table), columns=sql.SQL(',').join(map(sql.Identifier,all_columns)),
            temp=sql.Identifier(temp), key=sql.Identifier(key),
            updates=sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(c),sql.Identifier(c)) for c in updates)))
    return {'scanned': len(rows), **counts}


def transform(conn, run_id):
    counts = {}
    for table,(key,fields,select) in MODELS.items():
        compared = fields[1:]
        updates = compared + ['_run_id']
        result = conn.execute(sql.SQL('''INSERT INTO foodflow_analytics.{table} AS current ({columns},_run_id)
            SELECT source.*, %s::uuid FROM ({select}) source WHERE true
            ON CONFLICT ({key}) DO UPDATE SET {updates}
            WHERE ROW({current}) IS DISTINCT FROM ROW({excluded})''').format(
                table=sql.Identifier(table), columns=sql.SQL(',').join(map(sql.Identifier,fields)),
                select=sql.SQL(select), key=sql.Identifier(key),
                updates=sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(c),sql.Identifier(c)) for c in updates),
                current=sql.SQL(',').join(sql.SQL('current.{}').format(sql.Identifier(c)) for c in compared),
                excluded=sql.SQL(',').join(sql.SQL('EXCLUDED.{}').format(sql.Identifier(c)) for c in compared)), (run_id,))
        counts[table] = {'changed': result.rowcount}
    return counts


def validate_warehouse(conn):
    for table,source in [('dim_customer','users'),('dim_restaurant','restaurant'),('dim_food','food'),('fact_orders','orders'),('fact_order_items','order_items'),('fact_reviews','reviews')]:
        result = conn.execute(sql.SQL('SELECT (SELECT COUNT(*) FROM foodflow_raw.{})=(SELECT COUNT(*) FROM foodflow_analytics.{}) AS valid').format(sql.Identifier(source),sql.Identifier(table))).fetchone()
        if not result['valid']:
            raise QualityError(f'{table}: warehouse row count mismatch')
    mismatch = conn.execute('''SELECT COUNT(*) AS n FROM foodflow_analytics.fact_orders o
        LEFT JOIN (SELECT order_id,SUM(line_total) AS subtotal FROM foodflow_analytics.fact_order_items GROUP BY order_id) i USING(order_id)
        WHERE i.subtotal IS NULL OR ABS(i.subtotal+o.delivery_fee-o.order_total)>0.02''').fetchone()['n']
    if mismatch:
        raise QualityError('fact_orders: warehouse total reconciliation mismatch')
    mismatch = conn.execute('''SELECT COUNT(*) AS n FROM foodflow_analytics.fact_order_items i
        JOIN foodflow_analytics.fact_orders o USING(order_id) WHERE i.restaurant_key<>o.restaurant_key''').fetchone()['n']
    if mismatch:
        raise QualityError('fact_order_items: warehouse restaurant mismatch')
    mismatch = conn.execute('''SELECT COUNT(*) AS n FROM foodflow_analytics.fact_reviews v
        JOIN foodflow_analytics.fact_orders o USING(order_id)
        WHERE v.customer_key<>o.customer_key OR v.restaurant_key<>o.restaurant_key''').fetchone()['n']
    if mismatch:
        raise QualityError('fact_reviews: warehouse order identity mismatch')


def run(dsn, directory):
    """Publish a complete validated source snapshot; never delete source records."""
    run_id, start = uuid.uuid4(), time.monotonic()
    with locked_connection(dsn) as conn:
        migrate(conn)
        # No other cooperating writer owns the lock. Leftover RUNNING rows mean
        # a previous process died; do not silently present them as successful.
        conn.execute("UPDATE foodflow_ops.runs SET status='ABANDONED',finished_at=clock_timestamp(),error_code='PROCESS_INTERRUPTED',error_detail='Previous writer terminated before publication' WHERE status='RUNNING'")
        conn.execute("INSERT INTO foodflow_ops.runs(run_id,status) VALUES(%s,'RUNNING')", (run_id,))
        event('run_started',run_id=run_id)
        manifest, counts = {}, {}
        try:
            snapshot, manifest = load_snapshot(Path(directory),manifest=manifest)
            event('source_validated',run_id=run_id,rows=sum(len(v) for v in snapshot.values()))
            with conn.transaction():
                for table, rows in snapshot.items():
                    counts[table] = raw_upsert(conn,table,rows,run_id)
                    event('source_compared',run_id=run_id,table=table,**counts[table])
                model_counts = transform(conn,run_id)
                validate_warehouse(conn)
                counts['models'] = model_counts
                duration = round((time.monotonic()-start)*1000)
                conn.execute("""UPDATE foodflow_ops.runs SET status='SUCCESS',quality_status='PASS',
                    finished_at=clock_timestamp(),duration_ms=%s,source_manifest=%s,row_counts=%s WHERE run_id=%s""",
                    (duration,Jsonb(manifest),Jsonb(counts),run_id))
        except Exception as exc:
            code = 'QUALITY_REJECTED' if isinstance(exc,QualityError) else getattr(exc,'sqlstate',None) or type(exc).__name__
            detail = str(exc) if isinstance(exc,QualityError) else 'Warehouse transaction failed; no data was published'
            conn.execute("""UPDATE foodflow_ops.runs SET status='FAILED',quality_status=%s,
                finished_at=clock_timestamp(),duration_ms=%s,source_manifest=%s,row_counts=%s,error_code=%s,error_detail=%s WHERE run_id=%s""",
                ('FAIL' if isinstance(exc,QualityError) else 'ERROR',round((time.monotonic()-start)*1000),Jsonb(manifest),Jsonb({'attempted':counts,'committed':False}),code,detail,run_id))
            event('run_failed',run_id=run_id,error_code=code,error_detail=detail)
            raise RunFailed(run_id,code,detail) from None
        # Logging after commit cannot relabel a successful publication as FAILED.
        event('run_published',run_id=run_id,duration_ms=duration)
        return {'run_id':str(run_id),'status':'SUCCESS','quality':'PASS','duration_ms':duration,'counts':counts}

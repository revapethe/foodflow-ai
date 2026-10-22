"""Portable read-only input snapshot and fingerprint for offline and serving use."""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.config import DB

VERSION = 1


@contextmanager
def warehouse():
    if os.getenv('FOODFLOW_DATABASE_URL'):
        from api.database import PostgresConnection
        db = PostgresConnection(os.environ['FOODFLOW_DATABASE_URL'])
    else:
        path = Path(os.getenv('FOODFLOW_DB_PATH', str(DB))).resolve()
        db = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
    try:
        yield db
    finally:
        db.close()


def snapshot(db):
    db.execute('BEGIN')
    rows = db.execute('''SELECT o.order_date AS date,r.city,COUNT(*) AS orders,
        COUNT(CASE WHEN o.status='delivered' THEN 1 END) AS delivered_orders,
        COUNT(CASE WHEN o.status='delivered' AND o.delivery_minutes IS NOT NULL THEN 1 END) AS duration_observations,
        ROUND(SUM(CASE WHEN o.status='delivered' THEN o.order_total ELSE 0 END),2) AS revenue,
        ROUND(AVG(CASE WHEN o.status='delivered' THEN o.delivery_minutes END),6) AS delivery_minutes
        FROM fact_orders o JOIN dim_restaurant r ON r.restaurant_key=o.restaurant_key
        GROUP BY o.order_date,r.city ORDER BY o.order_date,r.city''')
    normalized = []
    for row in rows:
        normalized.append({'date':str(row['date']), 'city':row['city'], 'orders':int(row['orders']),
            'delivered_orders':int(row['delivered_orders']), 'duration_observations':int(row['duration_observations']), 'revenue':round(float(row['revenue']),2),
            'delivery_minutes':None if row['delivery_minutes'] is None else round(float(row['delivery_minutes']),6)})
    digest = hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return normalized, digest

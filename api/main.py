"""Read-only analytics API over the SQLite or PostgreSQL dimensional warehouse."""
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from src.config import DB
from api.database import PostgresConnection, WarehouseUnavailable
from api.intelligence import insights

app = FastAPI(title="FoodFlow Intelligence API", version="1.0.0")


def connection():
    path = Path(os.getenv("FOODFLOW_DB_PATH", str(DB))).resolve()
    try:
        if os.getenv('FOODFLOW_DATABASE_URL'):
            db = PostgresConnection(os.environ['FOODFLOW_DATABASE_URL'])
        else:
            # FastAPI workers may hand off this request-scoped connection.
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only = ON")
        yield db
    except (sqlite3.Error, WarehouseUnavailable) as exc:
        detail = "PostgreSQL analytics unavailable. Check the read-only role, migrations and successful ETL publication." if os.getenv('FOODFLOW_DATABASE_URL') else "Analytics warehouse unavailable. Run python -m src.pipeline build."
        raise HTTPException(503, detail) from exc
    finally:
        if "db" in locals():
            db.close()


@app.get("/health")
def health(db: Annotated[sqlite3.Connection, Depends(connection)]):
    if db.execute("SELECT order_id FROM fact_orders LIMIT 1").fetchone() is None:
        raise HTTPException(503, "Analytics warehouse has no published orders. Run the selected ETL workflow.")
    return {"status": "ok"}


@app.get("/analytics")
def analytics(
    db: Annotated[sqlite3.Connection, Depends(connection)],
    city: Annotated[str | None, Query(max_length=100)] = None,
    start: date | None = None,
    end: date | None = None,
):
    if start and end and start > end:
        raise HTTPException(422, "start must be on or before end")
    clauses, params = ["1=1"], []
    for expression, value in [("r.city = ?", city), ("o.order_date >= ?", start), ("o.order_date <= ?", end)]:
        if value is not None:
            clauses.append(expression)
            params.append(str(value))
    where = " AND ".join(clauses)
    cte = f"""WITH selected AS (
        SELECT o.*, r.restaurant_name, r.city, r.cuisine
        FROM fact_orders o JOIN dim_restaurant r ON r.restaurant_key=o.restaurant_key
        WHERE {where}
    ) """

    def rows(sql):
        return [dict(row) for row in db.execute(cte + sql, params)]

    # One read transaction gives every panel a consistent warehouse snapshot.
    db.execute("BEGIN")
    bounds = dict(db.execute("SELECT MIN(order_date) AS start, MAX(order_date) AS end FROM fact_orders").fetchone())
    if bounds["start"] is None:
        raise HTTPException(503, "Analytics warehouse has no published orders. Run the selected ETL workflow.")
    cities = [r["city"] for r in db.execute("SELECT DISTINCT city FROM dim_restaurant ORDER BY city")]
    kpis = rows("""SELECT COUNT(*) AS all_orders,
        COUNT(CASE WHEN status='delivered' THEN 1 END) AS delivered_orders,
        COUNT(CASE WHEN status='cancelled' THEN 1 END) AS cancelled_orders,
        COUNT(CASE WHEN status='refunded' THEN 1 END) AS refunded_orders,
        COUNT(CASE WHEN status='delivered' AND delivery_minutes>60 THEN 1 END) AS over_60_min_orders,
        ROUND(COALESCE(SUM(CASE WHEN status='delivered' THEN order_total END),0),2) AS revenue,
        ROUND(AVG(CASE WHEN status='delivered' THEN order_total END),2) AS average_order_value,
        ROUND(AVG(CASE WHEN status='delivered' THEN delivery_minutes END),1) AS average_delivery_minutes,
        ROUND(100.0*COUNT(CASE WHEN status='delivered' THEN 1 END)/NULLIF(COUNT(*),0),1) AS fulfillment_rate
        FROM selected""")[0]
    kpis["average_rating"] = rows("""SELECT ROUND(AVG(v.rating),2) AS rating
        FROM fact_reviews v JOIN selected o ON o.order_id=v.order_id""")[0]["rating"]
    kpis['units_sold'] = rows("SELECT COALESCE(SUM(i.quantity),0) AS n FROM selected o JOIN fact_order_items i ON i.order_id=o.order_id WHERE o.status='delivered'")[0]['n']
    kpis['units_per_delivered_order'] = round(float(kpis['units_sold'])/kpis['delivered_orders'],2) if kpis['delivered_orders'] else None
    kpis['over_60_min_percent'] = round(100*kpis['over_60_min_orders']/kpis['delivered_orders'],2) if kpis['delivered_orders'] else None
    kpis['cancellation_percent'] = round(100*kpis['cancelled_orders']/kpis['all_orders'],2) if kpis['all_orders'] else None
    daily = rows("""SELECT order_date AS date, COUNT(*) AS orders,
        COUNT(CASE WHEN status='delivered' THEN 1 END) AS delivered_orders,
        ROUND(SUM(CASE WHEN status='delivered' THEN order_total ELSE 0 END),2) AS revenue
        FROM selected GROUP BY order_date ORDER BY order_date""")
    restaurants = rows("""SELECT restaurant_key, restaurant_name, city, cuisine,
        COUNT(*) AS orders, ROUND(SUM(order_total),2) AS revenue,
        ROUND(AVG(delivery_minutes),1) AS delivery_minutes
        FROM selected WHERE status='delivered' GROUP BY restaurant_key,restaurant_name,city,cuisine
        ORDER BY revenue DESC, restaurant_key LIMIT 10""")
    products = rows("""SELECT f.food_name, f.category, SUM(i.quantity) AS units,
        ROUND(SUM(i.line_total),2) AS revenue
        FROM selected o JOIN fact_order_items i ON i.order_id=o.order_id
        JOIN dim_food f ON f.food_key=i.food_key WHERE o.status='delivered'
        GROUP BY f.food_key,f.food_name,f.category ORDER BY units DESC,f.food_key LIMIT 10""")
    statuses = rows("SELECT status, COUNT(*) AS orders FROM selected GROUP BY status ORDER BY status")
    return {"source": "Bundled synthetic delivery data · " + ("PostgreSQL warehouse" if isinstance(db,PostgresConnection) else "SQLite warehouse"),
            "filters": {"city": city, "start": start, "end": end},
            "available": {"cities": cities, **bounds}, "kpis": kpis, "daily": daily,
            "restaurants": restaurants, "products": products, "statuses": statuses,
            "forecast": {"status": "separate_endpoint", "reason": "Evaluated forecasts and freshness checks are available from /intelligence."}}


@app.get('/intelligence')
def intelligence(
    db: Annotated[sqlite3.Connection, Depends(connection)],
    city: Annotated[str | None, Query(max_length=100)] = None,
    start: date | None = None,
    end: date | None = None,
):
    if start and end and start>end:
        raise HTTPException(422, 'start must be on or before end')
    return insights(db,city,start,end)

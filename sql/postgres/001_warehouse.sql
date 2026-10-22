-- Phase 2 schema v1: explicit keys, typed money, constraints, and lineage.
CREATE SCHEMA IF NOT EXISTS foodflow_ops;
CREATE SCHEMA IF NOT EXISTS foodflow_raw;
CREATE SCHEMA IF NOT EXISTS foodflow_analytics;
CREATE TABLE IF NOT EXISTS foodflow_ops.schema_versions (
    version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS foodflow_ops.runs (
    run_id uuid PRIMARY KEY,
    status text NOT NULL CHECK(status IN ('RUNNING','SUCCESS','FAILED','ABANDONED')),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    duration_ms bigint,
    source_manifest jsonb NOT NULL DEFAULT '{}',
    row_counts jsonb NOT NULL DEFAULT '{}',
    quality_status text NOT NULL DEFAULT 'PENDING',
    error_code text,
    error_detail text
);
CREATE INDEX IF NOT EXISTS runs_started_idx ON foodflow_ops.runs(started_at DESC);


CREATE TABLE IF NOT EXISTS foodflow_raw.users (
    user_id integer NOT NULL PRIMARY KEY CHECK (user_id > 0),
    user_name text NOT NULL CHECK (length(btrim(user_name)) BETWEEN 1 AND 10000),
    city text NOT NULL CHECK (length(btrim(city)) BETWEEN 1 AND 10000),
    signup_date date NOT NULL,
    _row_hash text NOT NULL CHECK(length(_row_hash)=64),
    _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id),
    _loaded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS foodflow_raw.restaurant (
    restaurant_id integer NOT NULL PRIMARY KEY CHECK (restaurant_id > 0),
    restaurant_name text NOT NULL CHECK (length(btrim(restaurant_name)) BETWEEN 1 AND 10000),
    city text NOT NULL CHECK (length(btrim(city)) BETWEEN 1 AND 10000),
    cuisine text NOT NULL CHECK (length(btrim(cuisine)) BETWEEN 1 AND 10000),
    _row_hash text NOT NULL CHECK(length(_row_hash)=64),
    _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id),
    _loaded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS foodflow_raw.food (
    food_id integer NOT NULL PRIMARY KEY CHECK (food_id > 0),
    food_name text NOT NULL CHECK (length(btrim(food_name)) BETWEEN 1 AND 10000),
    category text NOT NULL CHECK (length(btrim(category)) BETWEEN 1 AND 10000),
    _row_hash text NOT NULL CHECK(length(_row_hash)=64),
    _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id),
    _loaded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS foodflow_raw.menu (
    menu_id integer NOT NULL PRIMARY KEY CHECK (menu_id > 0),
    restaurant_id integer NOT NULL CHECK (restaurant_id > 0) REFERENCES foodflow_raw.restaurant(restaurant_id),
    food_id integer NOT NULL CHECK (food_id > 0) REFERENCES foodflow_raw.food(food_id),
    price numeric(12,2) NOT NULL CHECK (price >= 0),
    _row_hash text NOT NULL CHECK(length(_row_hash)=64),
    _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id),
    _loaded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK(price > 0)
);

CREATE TABLE IF NOT EXISTS foodflow_raw.orders (
    order_id integer NOT NULL PRIMARY KEY CHECK (order_id > 0),
    user_id integer NOT NULL CHECK (user_id > 0) REFERENCES foodflow_raw.users(user_id),
    restaurant_id integer NOT NULL CHECK (restaurant_id > 0) REFERENCES foodflow_raw.restaurant(restaurant_id),
    ordered_at timestamp without time zone NOT NULL,
    status text NOT NULL CHECK (length(btrim(status)) BETWEEN 1 AND 10000),
    payment_method text NOT NULL CHECK (length(btrim(payment_method)) BETWEEN 1 AND 10000),
    delivery_minutes integer CHECK (delivery_minutes > 0),
    delivery_fee numeric(12,2) NOT NULL CHECK (delivery_fee >= 0),
    order_total numeric(12,2) NOT NULL CHECK (order_total >= 0),
    _row_hash text NOT NULL CHECK(length(_row_hash)=64),
    _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id),
    _loaded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK(status IN ('delivered','cancelled','refunded')),
    CHECK(payment_method IN ('card','wallet','cash')),
    CHECK(status <> 'delivered' OR delivery_minutes IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS foodflow_raw.order_items (
    order_item_id integer NOT NULL PRIMARY KEY CHECK (order_item_id > 0),
    order_id integer NOT NULL CHECK (order_id > 0) REFERENCES foodflow_raw.orders(order_id),
    menu_id integer NOT NULL CHECK (menu_id > 0) REFERENCES foodflow_raw.menu(menu_id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(12,2) NOT NULL CHECK (unit_price >= 0),
    line_total numeric(12,2) NOT NULL CHECK (line_total >= 0),
    _row_hash text NOT NULL CHECK(length(_row_hash)=64),
    _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id),
    _loaded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK(unit_price > 0),
    CHECK(abs(line_total-quantity*unit_price) <= 0.01)
);

CREATE TABLE IF NOT EXISTS foodflow_raw.reviews (
    review_id integer NOT NULL PRIMARY KEY CHECK (review_id > 0),
    order_id integer NOT NULL CHECK (order_id > 0) REFERENCES foodflow_raw.orders(order_id),
    user_id integer NOT NULL CHECK (user_id > 0) REFERENCES foodflow_raw.users(user_id),
    restaurant_id integer NOT NULL CHECK (restaurant_id > 0) REFERENCES foodflow_raw.restaurant(restaurant_id),
    rating integer NOT NULL CHECK (rating > 0),
    review_text text NOT NULL CHECK (length(btrim(review_text)) BETWEEN 1 AND 10000),
    _row_hash text NOT NULL CHECK(length(_row_hash)=64),
    _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id),
    _loaded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK(rating BETWEEN 1 AND 5)
);


CREATE TABLE IF NOT EXISTS foodflow_analytics.dim_customer (
 customer_key integer PRIMARY KEY, user_name text NOT NULL, city text NOT NULL, signup_date date NOT NULL,
 _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id)
);
CREATE TABLE IF NOT EXISTS foodflow_analytics.dim_restaurant (
 restaurant_key integer PRIMARY KEY, restaurant_name text NOT NULL, city text NOT NULL, cuisine text NOT NULL,
 _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id)
);
CREATE TABLE IF NOT EXISTS foodflow_analytics.dim_food (
 food_key integer PRIMARY KEY, food_name text NOT NULL, category text NOT NULL,
 _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id)
);
CREATE TABLE IF NOT EXISTS foodflow_analytics.fact_orders (
 order_id integer PRIMARY KEY,
 customer_key integer NOT NULL REFERENCES foodflow_analytics.dim_customer,
 restaurant_key integer NOT NULL REFERENCES foodflow_analytics.dim_restaurant,
 ordered_at timestamp without time zone NOT NULL, order_date date NOT NULL,
 status text NOT NULL CHECK(status IN ('delivered','cancelled','refunded')),
 payment_method text NOT NULL, delivery_minutes integer CHECK(delivery_minutes > 0),
 delivery_fee numeric(12,2) NOT NULL CHECK(delivery_fee >= 0),
 order_total numeric(12,2) NOT NULL CHECK(order_total >= 0),
 _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id)
);
CREATE INDEX IF NOT EXISTS fact_orders_date_idx ON foodflow_analytics.fact_orders(order_date);
CREATE INDEX IF NOT EXISTS fact_orders_restaurant_idx ON foodflow_analytics.fact_orders(restaurant_key);
CREATE TABLE IF NOT EXISTS foodflow_analytics.fact_order_items (
 order_item_id integer PRIMARY KEY,
 order_id integer NOT NULL REFERENCES foodflow_analytics.fact_orders,
 restaurant_key integer NOT NULL REFERENCES foodflow_analytics.dim_restaurant,
 food_key integer NOT NULL REFERENCES foodflow_analytics.dim_food,
 quantity integer NOT NULL CHECK(quantity > 0), unit_price numeric(12,2) NOT NULL CHECK(unit_price > 0),
 line_total numeric(12,2) NOT NULL CHECK(line_total >= 0),
 _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id),
 CHECK(abs(line_total-quantity*unit_price) <= 0.01)
);
CREATE INDEX IF NOT EXISTS fact_items_order_idx ON foodflow_analytics.fact_order_items(order_id);
CREATE TABLE IF NOT EXISTS foodflow_analytics.fact_reviews (
 review_id integer PRIMARY KEY,
 order_id integer NOT NULL REFERENCES foodflow_analytics.fact_orders,
 customer_key integer NOT NULL REFERENCES foodflow_analytics.dim_customer,
 restaurant_key integer NOT NULL REFERENCES foodflow_analytics.dim_restaurant,
 rating integer NOT NULL CHECK(rating BETWEEN 1 AND 5), review_text text NOT NULL,
 _run_id uuid NOT NULL REFERENCES foodflow_ops.runs(run_id)
);
CREATE INDEX IF NOT EXISTS fact_reviews_order_idx ON foodflow_analytics.fact_reviews(order_id);

CREATE OR REPLACE VIEW foodflow_analytics.mart_daily_sales AS
 SELECT order_date,COUNT(*) AS delivered_orders,ROUND(SUM(order_total),2) AS revenue,
 ROUND(AVG(order_total),2) AS avg_order_value FROM foodflow_analytics.fact_orders
 WHERE status='delivered' GROUP BY order_date;
CREATE OR REPLACE VIEW foodflow_analytics.mart_restaurant_performance AS
 SELECT r.restaurant_key,r.restaurant_name,r.city,r.cuisine,COUNT(o.order_id) AS delivered_orders,
 ROUND(COALESCE(SUM(o.order_total),0),2) AS revenue,ROUND(AVG(o.delivery_minutes),1) AS avg_delivery_minutes,
 (SELECT ROUND(AVG(v.rating),2) FROM foodflow_analytics.fact_reviews v WHERE v.restaurant_key=r.restaurant_key) AS avg_rating
 FROM foodflow_analytics.dim_restaurant r LEFT JOIN foodflow_analytics.fact_orders o
 ON r.restaurant_key=o.restaurant_key AND o.status='delivered'
 GROUP BY r.restaurant_key,r.restaurant_name,r.city,r.cuisine;
CREATE OR REPLACE VIEW foodflow_analytics.mart_top_foods AS
 SELECT f.food_name,f.category,SUM(i.quantity) AS units_sold,ROUND(SUM(i.line_total),2) AS item_revenue
 FROM foodflow_analytics.fact_order_items i JOIN foodflow_analytics.dim_food f ON i.food_key=f.food_key
 JOIN foodflow_analytics.fact_orders o ON i.order_id=o.order_id WHERE o.status='delivered'
 GROUP BY f.food_key,f.food_name,f.category;
CREATE OR REPLACE VIEW foodflow_analytics.mart_kpis AS
 SELECT 'delivered_orders' AS metric,COUNT(*)::numeric AS value FROM foodflow_analytics.fact_orders WHERE status='delivered'
 UNION ALL SELECT 'revenue',ROUND(COALESCE(SUM(order_total),0),2) FROM foodflow_analytics.fact_orders WHERE status='delivered'
 UNION ALL SELECT 'average_rating',ROUND(AVG(rating),2) FROM foodflow_analytics.fact_reviews
 UNION ALL SELECT 'all_orders',COUNT(*) FROM foodflow_analytics.fact_orders;
INSERT INTO foodflow_ops.schema_versions(version) VALUES(1) ON CONFLICT DO NOTHING;

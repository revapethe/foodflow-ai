DROP TABLE IF EXISTS dim_customer;
CREATE TABLE dim_customer AS SELECT user_id AS customer_key,user_name,city,signup_date FROM stg_users;
DROP TABLE IF EXISTS dim_restaurant;
CREATE TABLE dim_restaurant AS SELECT restaurant_id AS restaurant_key,restaurant_name,city,cuisine FROM stg_restaurant;
DROP TABLE IF EXISTS dim_food;
CREATE TABLE dim_food AS SELECT food_id AS food_key,food_name,category FROM stg_food;
DROP TABLE IF EXISTS fact_order_items;
CREATE TABLE fact_order_items AS
 SELECT oi.order_item_id,oi.order_id,m.restaurant_id AS restaurant_key,m.food_id AS food_key,oi.quantity,oi.unit_price,oi.line_total
 FROM stg_order_items oi JOIN stg_menu m ON oi.menu_id=m.menu_id;
DROP TABLE IF EXISTS fact_orders;
CREATE TABLE fact_orders AS
 SELECT order_id,user_id AS customer_key,restaurant_id AS restaurant_key,ordered_at,substr(ordered_at,1,10) AS order_date,status,payment_method,delivery_minutes,delivery_fee,order_total FROM stg_orders;
DROP TABLE IF EXISTS fact_reviews;
CREATE TABLE fact_reviews AS SELECT review_id,order_id,user_id AS customer_key,restaurant_id AS restaurant_key,rating,review_text FROM stg_reviews;
CREATE INDEX IF NOT EXISTS ix_fact_orders_date ON fact_orders(order_date);
CREATE INDEX IF NOT EXISTS ix_fact_items_order ON fact_order_items(order_id);
DROP VIEW IF EXISTS mart_daily_sales;
CREATE VIEW mart_daily_sales AS SELECT order_date,COUNT(*) AS delivered_orders,ROUND(SUM(order_total),2) AS revenue,ROUND(AVG(order_total),2) AS avg_order_value FROM fact_orders WHERE status='delivered' GROUP BY order_date;
DROP VIEW IF EXISTS mart_restaurant_performance;
CREATE VIEW mart_restaurant_performance AS SELECT r.restaurant_key,r.restaurant_name,r.city,r.cuisine,COUNT(o.order_id) AS delivered_orders,ROUND(COALESCE(SUM(o.order_total),0),2) AS revenue,ROUND(AVG(o.delivery_minutes),1) AS avg_delivery_minutes,(SELECT ROUND(AVG(v.rating),2) FROM fact_reviews v WHERE v.restaurant_key=r.restaurant_key) AS avg_rating FROM dim_restaurant r LEFT JOIN fact_orders o ON r.restaurant_key=o.restaurant_key AND o.status='delivered' GROUP BY r.restaurant_key,r.restaurant_name,r.city,r.cuisine;
DROP VIEW IF EXISTS mart_top_foods;
CREATE VIEW mart_top_foods AS SELECT f.food_name,f.category,SUM(i.quantity) AS units_sold,ROUND(SUM(i.line_total),2) AS item_revenue FROM fact_order_items i JOIN dim_food f ON i.food_key=f.food_key JOIN fact_orders o ON i.order_id=o.order_id WHERE o.status='delivered' GROUP BY f.food_key,f.food_name,f.category;
DROP VIEW IF EXISTS mart_kpis;
CREATE VIEW mart_kpis AS SELECT 'delivered_orders' AS metric,COUNT(*) AS value FROM fact_orders WHERE status='delivered' UNION ALL SELECT 'revenue',ROUND(COALESCE(SUM(order_total),0),2) FROM fact_orders WHERE status='delivered' UNION ALL SELECT 'average_rating',ROUND(AVG(rating),2) FROM fact_reviews UNION ALL SELECT 'all_orders',COUNT(*) FROM fact_orders;

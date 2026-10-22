"""Check a running Phase 1 web proxy against the actual read-only warehouse.

Run from the repository root: python scripts/verify_phase1.py
No database modifications or mocked responses are used.
"""
import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


def verify(web_url, path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        cities = [r[0] for r in db.execute('SELECT DISTINCT city FROM dim_restaurant ORDER BY city')]
        cases = [{}, *[{'city': c} for c in cities],
                 {'city': 'Denver', 'start': '2025-03-01', 'end': '2025-06-30'},
                 {'start': '2025-01-01', 'end': '2025-01-01'},
                 {'start': '2099-01-01'}]
        for filters in cases:
            with urlopen(web_url.rstrip('/') + '/api/analytics?' + urlencode(filters), timeout=20) as response:
                data = json.load(response)
            conditions, params = [], []
            for key, sql in [('city', 'r.city=?'), ('start', 'o.order_date>=?'), ('end', 'o.order_date<=?')]:
                if key in filters:
                    conditions.append(sql); params.append(filters[key])
            where = ' AND '.join(conditions) or '1=1'
            query = f'''SELECT o.* FROM fact_orders o JOIN dim_restaurant r
                ON o.restaurant_key=r.restaurant_key WHERE {where}'''
            selected = f'WITH s AS ({query}) '
            def rows(sql):
                return [dict(r) for r in db.execute(selected + sql, params)]
            expected = rows('''SELECT COUNT(*) AS all_orders,
                COUNT(CASE WHEN status='delivered' THEN 1 END) AS delivered_orders,
                ROUND(COALESCE(SUM(CASE WHEN status='delivered' THEN order_total END),0),2) AS revenue,
                ROUND(AVG(CASE WHEN status='delivered' THEN order_total END),2) AS average_order_value,
                ROUND(AVG(CASE WHEN status='delivered' THEN delivery_minutes END),1) AS average_delivery_minutes,
                ROUND(100.0*COUNT(CASE WHEN status='delivered' THEN 1 END)/NULLIF(COUNT(*),0),1) AS fulfillment_rate
                FROM s''')[0]
            expected['average_rating'] = rows('SELECT ROUND(AVG(v.rating),2) AS rating FROM fact_reviews v JOIN s ON s.order_id=v.order_id')[0]['rating']
            assert {k:data['kpis'][k] for k in expected} == expected, (filters, data['kpis'], expected)
            assert data['statuses'] == rows('SELECT status,COUNT(*) AS orders FROM s GROUP BY status ORDER BY status')
            assert data['daily'] == rows('''SELECT order_date AS date,COUNT(*) AS orders,
                COUNT(CASE WHEN status='delivered' THEN 1 END) AS delivered_orders,
                ROUND(SUM(CASE WHEN status='delivered' THEN order_total ELSE 0 END),2) AS revenue
                FROM s GROUP BY order_date ORDER BY order_date''')
            assert data['products'] == rows('''SELECT f.food_name,f.category,SUM(i.quantity) AS units,
                ROUND(SUM(i.line_total),2) AS revenue FROM s
                JOIN fact_order_items i ON i.order_id=s.order_id JOIN dim_food f ON f.food_key=i.food_key
                WHERE s.status='delivered' GROUP BY f.food_key,f.food_name,f.category ORDER BY units DESC,f.food_key LIMIT 10''')
            assert data['restaurants'] == rows('''SELECT r.restaurant_key,r.restaurant_name,r.city,r.cuisine,
                COUNT(*) AS orders,ROUND(SUM(s.order_total),2) AS revenue,
                ROUND(AVG(s.delivery_minutes),1) AS delivery_minutes FROM s
                JOIN dim_restaurant r ON r.restaurant_key=s.restaurant_key WHERE s.status='delivered'
                GROUP BY r.restaurant_key,r.restaurant_name,r.city,r.cuisine
                ORDER BY revenue DESC,r.restaurant_key LIMIT 10''')
            print(json.dumps({'filters': filters, 'orders': expected['all_orders'], 'revenue': expected['revenue'], 'result': 'PASS'}))
        print(f'{len(cases)} live warehouse/proxy cases passed; all KPI and chart/table series reconciled.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-url', default='http://127.0.0.1:3000')
    parser.add_argument('--database', type=Path, default=Path(__file__).resolve().parents[1] / 'warehouse/foodflow.db')
    args = parser.parse_args()
    verify(args.web_url, args.database)

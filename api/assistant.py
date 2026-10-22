"""Free, deterministic natural-language analytics over approved SQL templates.

This is a bounded semantic parser, not a general-purpose language model. Unknown
or ambiguous questions never become SQL. Only extracted values are bound.
"""
import re
from datetime import date, datetime, timezone
import calendar

EXAMPLES = ["What is total revenue?", "How many orders in Denver?", "Show delivery performance",
            "Top 5 restaurants by revenue", "Top 5 foods by units", "Show monthly revenue",
            "Compare cities", "What is revenue in March 2025?"]
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
INTENTS = {
    'revenue': r'(?:what is |show |give me )?(?:the )?(?:total |delivered )?revenue',
    'orders': r'(?:how many |show |what is |what are )?(?:the |total )?orders(?: are there)?',
    'delivery': r'(?:show |what is |what are )?(?:the |average )?(?:delivery performance|delivery time|delivery times)',
    'cancellations': r'(?:show |what is |what are |how many )?(?:the )?(?:cancellations|cancelled orders|cancellation rate)',
    'restaurants': r'(?:show |what are )?(?:the )?top(?: (\d+))? restaurants(?: by (?:delivered )?revenue)?',
    'foods': r'(?:show |what are )?(?:the )?top(?: (\d+))? (?:foods|products)(?: by (?:units|units sold))?',
    'trend': r'(?:show |what is )?(?:the )?monthly (?:revenue|revenue trend)',
    'cities': r'(?:show |compare )?(?:the )?(?:cities|city performance)',
    'summary': r'(?:show |give me )?(?:a |the )?(?:summary|overview)',
}


def parse(question, cities, city=None, start=None, end=None):
    text = re.sub(r'\s+', ' ', question.strip().lower()).rstrip('?.!')
    text = re.sub(r'^please | please$', '', text)
    # Scope phrases are explicit and removed before matching the whole intent.
    found = []
    for candidate in cities:
        pattern = r'\b' + re.escape(candidate.lower()) + r'\b'
        if re.search(pattern, text):
            found.append(candidate)
            text = re.sub(pattern, '', text)
    if len(found) > 1:
        raise ValueError('Ask about one city at a time, or use “Compare cities”.')
    if found:
        city = found[0]
    if city is not None and city not in cities:
        raise ValueError('Choose a known market from the dashboard filter.')
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text)
    month = re.search(r'\b(' + '|'.join(MONTHS) + r') (\d{4})\b', text)
    years = re.findall(r'\b(?:19|20)\d{2}\b', text) if not dates and not month else []
    if dates:
        if len(dates) != 2 or month:
            raise ValueError('Use an inclusive range: from YYYY-MM-DD to YYYY-MM-DD.')
        phrase = re.search(r'\b(?:from |between )?' + re.escape(dates[0]) + r' (?:to|through|and) ' + re.escape(dates[1]) + r'\b', text)
        if not phrase:
            raise ValueError('Use an inclusive range: from YYYY-MM-DD to YYYY-MM-DD.')
        start, end = (date.fromisoformat(value) for value in dates)
        text = text[:phrase.start()] + text[phrase.end():]
    elif month:
        year, number = int(month[2]), MONTHS[month[1]]
        start, end = date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])
        text = text[:month.start()] + text[month.end():]
    elif years:
        if len(years) != 1:
            raise ValueError('Use one year or an explicit date range.')
        start, end = date(int(years[0]), 1, 1), date(int(years[0]), 12, 31)
        text = re.sub(r'\b' + years[0] + r'\b', '', text)
    # Only orphaned scope prepositions at the end can be discarded.
    text = text.strip()
    text = re.sub(r'(?:\s+(?:in|for|during|at))+$', '', text).strip()
    if start and end and start > end:
        raise ValueError('The start date must be on or before the end date.')
    for name, pattern in INTENTS.items():
        match = re.fullmatch(pattern, text)
        if match:
            limit = int(match[1]) if name in ('restaurants', 'foods') and match[1] else 10
            if not 1 <= limit <= 10:
                raise ValueError('Rankings support top 1 through top 10.')
            return name, city, start, end, limit
    raise ValueError('I could not reliably interpret that question. Try one of the supported examples. Relative dates, causal explanations, arbitrary SQL, and inventory questions are not supported.')


SUMMARY = """SELECT COUNT(*) AS all_orders,
    COUNT(CASE WHEN status='delivered' THEN 1 END) AS delivered_orders,
    COUNT(CASE WHEN status='cancelled' THEN 1 END) AS cancelled_orders,
    ROUND(COALESCE(SUM(CASE WHEN status='delivered' THEN order_total ELSE 0 END),0),2) AS delivered_revenue,
    ROUND(AVG(CASE WHEN status='delivered' THEN delivery_minutes END),1) AS average_delivery_minutes,
    COUNT(CASE WHEN status='delivered' AND delivery_minutes>60 THEN 1 END) AS deliveries_over_60_minutes,
    COUNT(CASE WHEN status='delivered' AND delivery_minutes IS NOT NULL THEN 1 END) AS delivery_time_observations
    FROM selected"""


def answer(db, question, city=None, start=None, end=None):
    db.execute('BEGIN')
    bounds = dict(db.execute('SELECT MIN(order_date) AS start, MAX(order_date) AS end FROM fact_orders').fetchone())
    cities = [r['city'] for r in db.execute('SELECT DISTINCT city FROM dim_restaurant ORDER BY city')]
    if bounds['start'] is None:
        return {'status': 'unavailable', 'answer': 'No published warehouse orders are available.', 'examples': EXAMPLES}
    try:
        intent, city, start, end, limit = parse(question, cities, city, start, end)
    except ValueError as exc:
        return {'status': 'clarification', 'answer': str(exc), 'examples': EXAMPLES, 'mode': 'deterministic semantic parser'}
    clauses, params = ['1=1'], []
    for expr, value in [('r.city = ?', city), ('o.order_date >= ?', start), ('o.order_date <= ?', end)]:
        if value is not None:
            clauses.append(expr)
            params.append(str(value))
    cte = '''WITH selected AS (
        SELECT o.order_id, o.restaurant_key, o.order_date, o.status, o.order_total, o.delivery_minutes,
               r.restaurant_name, r.city, r.cuisine
        FROM fact_orders o JOIN dim_restaurant r ON r.restaurant_key=o.restaurant_key
        WHERE ''' + ' AND '.join(clauses) + ')\n'
    scope = dict(db.execute(cte + 'SELECT COUNT(*) AS matching_orders, MIN(order_date) AS start, MAX(order_date) AS end FROM selected', params).fetchone())
    sql = SUMMARY
    if intent == 'restaurants':
        sql = '''SELECT restaurant_key, restaurant_name, city, COUNT(*) AS delivered_orders,
            ROUND(SUM(order_total),2) AS delivered_revenue FROM selected WHERE status='delivered'
            GROUP BY restaurant_key, restaurant_name, city ORDER BY delivered_revenue DESC, restaurant_key LIMIT ?'''
    elif intent == 'foods':
        sql = '''SELECT f.food_key, f.food_name, SUM(i.quantity) AS units,
            ROUND(SUM(i.line_total),2) AS item_revenue FROM selected o
            JOIN fact_order_items i ON i.order_id=o.order_id JOIN dim_food f ON f.food_key=i.food_key
            WHERE o.status='delivered' GROUP BY f.food_key,f.food_name ORDER BY units DESC,f.food_key LIMIT ?'''
    elif intent == 'trend':
        sql = '''SELECT SUBSTR(CAST(order_date AS TEXT),1,7) AS month, COUNT(*) AS all_orders,
            ROUND(SUM(CASE WHEN status='delivered' THEN order_total ELSE 0 END),2) AS delivered_revenue
            FROM selected GROUP BY SUBSTR(CAST(order_date AS TEXT),1,7) ORDER BY month DESC LIMIT 12'''
    elif intent == 'cities':
        sql = '''SELECT city, COUNT(*) AS all_orders,
            COUNT(CASE WHEN status='delivered' THEN 1 END) AS delivered_orders,
            ROUND(SUM(CASE WHEN status='delivered' THEN order_total ELSE 0 END),2) AS delivered_revenue
            FROM selected GROUP BY city ORDER BY delivered_revenue DESC,city LIMIT 20'''
    bound = [*params, limit] if intent in ('restaurants', 'foods') else params
    rows = [dict(row) for row in db.execute(cte + sql, bound)]
    count = scope['matching_orders']
    if not count:
        sentence = 'No orders match this city and date selection. No business conclusion can be drawn from an empty result.'
    elif intent in ('revenue', 'orders', 'delivery', 'cancellations', 'summary'):
        r = rows[0]
        if intent == 'revenue':
            sentence = f"Delivered-order revenue is ${float(r['delivered_revenue']):,.2f} across {r['delivered_orders']:,} delivered orders."
        elif intent == 'orders':
            sentence = f"There are {r['all_orders']:,} orders across all statuses; {r['delivered_orders']:,} were delivered."
        elif intent == 'delivery':
            average = 'unavailable' if r['average_delivery_minutes'] is None else f"{r['average_delivery_minutes']} minutes"
            sentence = f"Average delivered-order duration is {average}, based on {r['delivery_time_observations']:,} recorded durations. {r['deliveries_over_60_minutes']:,} delivered orders took over 60 minutes."
        elif intent == 'cancellations':
            sentence = f"There are {r['cancelled_orders']:,} cancelled orders out of {count:,} total orders ({100*r['cancelled_orders']/count:.2f}%)."
        else:
            sentence = f"The selection contains {count:,} orders, {r['delivered_orders']:,} delivered orders, and ${float(r['delivered_revenue']):,.2f} delivered-order revenue."
    else:
        sentence = {'restaurants': f'Top {len(rows)} restaurants ranked by delivered-order revenue.',
                    'foods': f'Top {len(rows)} foods ranked by units in delivered orders; item revenue excludes delivery fees.',
                    'trend': 'Monthly delivered-order revenue, showing up to the latest 12 observed months. Missing months are not imputed.',
                    'cities': 'City comparison ranked by delivered-order revenue, showing up to 20 cities.'}[intent]
    return {'status': 'answered', 'answer': sentence, 'intent': intent, 'rows': rows,
            'sql': cte + sql, 'parameters': bound,
            'filters': {'city': city, 'start': start, 'end': end}, 'matching_orders': count,
            'observed_range': scope, 'warehouse_range': bounds,
            'queried_at': datetime.now(timezone.utc).isoformat(),
            'source': 'Bundled synthetic data · actual warehouse query results',
            'mode': 'deterministic semantic parser',
            'notes': ['Question scopes override the corresponding dashboard filters; other dashboard filters remain active.',
                      'Date bounds are inclusive. Revenue includes delivered-order totals; it is not profit.',
                      'This free assistant uses supported SQL templates, not a general-purpose language model.'],
            'examples': EXAMPLES}

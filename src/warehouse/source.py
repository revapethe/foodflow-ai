"""Strict, deterministic full-snapshot contracts over the existing seven CSVs."""
import csv
import hashlib
import io
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Stable source IDs are the dimension keys (Type 1); no ID remapping on reruns.
SPECS = {
    'users': [('user_id','id'),('user_name','text'),('city','text'),('signup_date','date')],
    'restaurant': [('restaurant_id','id'),('restaurant_name','text'),('city','text'),('cuisine','text')],
    'food': [('food_id','id'),('food_name','text'),('category','text')],
    'menu': [('menu_id','id'),('restaurant_id','id'),('food_id','id'),('price','money')],
    'orders': [('order_id','id'),('user_id','id'),('restaurant_id','id'),('ordered_at','timestamp'),('status','text'),('payment_method','text'),('delivery_minutes','optional_int'),('delivery_fee','money'),('order_total','money')],
    'order_items': [('order_item_id','id'),('order_id','id'),('menu_id','id'),('quantity','id'),('unit_price','money'),('line_total','money')],
    'reviews': [('review_id','id'),('order_id','id'),('user_id','id'),('restaurant_id','id'),('rating','id'),('review_text','text')],
}


class QualityError(ValueError):
    """Contains safe contract identifiers, never source text or credentials."""


def canonical(row):
    return json.dumps(row, sort_keys=True, default=str, separators=(',',':'), ensure_ascii=False)


def parse(value, kind):
    value = value.strip()
    if kind == 'optional_int' and not value:
        return None
    if not value:
        raise ValueError('required value missing')
    if kind in ('id','optional_int'):
        n = Decimal(value)
        if not n.is_finite() or n != n.to_integral_value() or n < 1 or n > 2147483647:
            raise ValueError('positive 32-bit integer required')
        return int(n)
    if kind == 'money':
        n = Decimal(value)
        if not n.is_finite() or n < 0 or n >= Decimal('10000000000') or n != n.quantize(Decimal('.01')):
            raise ValueError('nonnegative money with at most two decimal places required')
        return n.quantize(Decimal('.01'))
    if kind == 'date':
        return date.fromisoformat(value)
    if kind == 'timestamp':
        result = datetime.fromisoformat(value)
        if result.tzinfo is not None:
            raise ValueError('source contract requires a timezone-naive timestamp')
        return result
    if len(value) > 10000:
        raise ValueError('text exceeds source contract')
    return value


def load_snapshot(directory: Path, manifest=None):
    frames = {}
    manifest = {} if manifest is None else manifest
    for table, specs in SPECS.items():
        try:
            payload = (directory / f'{table}.csv').read_bytes()
            manifest[table] = {'sha256': hashlib.sha256(payload).hexdigest(), 'rows': None}
            reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
            if reader.fieldnames != [name for name,_ in specs]:
                raise QualityError(f'{table}: schema mismatch')
            rows = []
            for line, source in enumerate(reader, 2):
                try:
                    if None in source or any(v is None for v in source.values()):
                        raise ValueError('malformed row')
                    rows.append({name: parse(source[name],kind) for name,kind in specs})
                except (ValueError, InvalidOperation, OverflowError):
                    raise QualityError(f'{table}: invalid typed value at CSV line {line}') from None
            key = specs[0][0]
            if len({r[key] for r in rows}) != len(rows):
                raise QualityError(f'{table}: duplicate primary key')
            if not rows and table != 'reviews':
                raise QualityError(f'{table}: required source is empty')
            frames[table] = rows
            manifest[table] = {'sha256': hashlib.sha256(payload).hexdigest(), 'rows': len(rows)}
        except (OSError, UnicodeError, csv.Error):
            raise QualityError(f'{table}: unreadable source CSV') from None
    validate_snapshot(frames)
    return frames, manifest


def validate_snapshot(data):
    keyed = {t:{r[SPECS[t][0][0]]:r for r in rows} for t,rows in data.items()}
    relations = [('menu','restaurant_id','restaurant'),('menu','food_id','food'),
        ('orders','user_id','users'),('orders','restaurant_id','restaurant'),
        ('order_items','order_id','orders'),('order_items','menu_id','menu'),
        ('reviews','order_id','orders'),('reviews','user_id','users'),('reviews','restaurant_id','restaurant')]
    for child,column,parent in relations:
        if any(r[column] not in keyed[parent] for r in data[child]):
            raise QualityError(f'{child}.{column}: foreign key violation')
    totals = {}
    for item in data['order_items']:
        order, menu = keyed['orders'][item['order_id']], keyed['menu'][item['menu_id']]
        if order['restaurant_id'] != menu['restaurant_id']:
            raise QualityError('order_items: menu/order restaurant mismatch')
        if item['unit_price'] <= 0 or abs(item['line_total'] - item['quantity']*item['unit_price']) > Decimal('.01'):
            raise QualityError('order_items: line arithmetic violation')
        totals[item['order_id']] = totals.get(item['order_id'], Decimal(0)) + item['line_total']
    for order in data['orders']:
        if order['status'] not in ('delivered','cancelled','refunded') or order['payment_method'] not in ('card','wallet','cash'):
            raise QualityError('orders: invalid status/payment domain')
        if order['status'] == 'delivered' and order['delivery_minutes'] is None:
            raise QualityError('orders: delivered order missing delivery duration')
        if order['order_id'] not in totals or abs(totals[order['order_id']] + order['delivery_fee'] - order['order_total']) > Decimal('.02'):
            raise QualityError('orders: total reconciliation violation')
    if any(row['price'] <= 0 for row in data['menu']):
        raise QualityError('menu: nonpositive price')
    for review in data['reviews']:
        order = keyed['orders'][review['order_id']]
        if review['rating'] > 5:
            raise QualityError('reviews: rating outside 1–5')
        if (review['user_id'], review['restaurant_id']) != (order['user_id'], order['restaurant_id']):
            raise QualityError('reviews: order identity mismatch')

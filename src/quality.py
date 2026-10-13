"""Fail-fast checks before any database is published."""
import pandas as pd
from .config import TABLES

KEYS={'users':'user_id','restaurant':'restaurant_id','food':'food_id','menu':'menu_id','orders':'order_id','order_items':'order_item_id','reviews':'review_id'}
FK=[('menu','restaurant_id','restaurant','restaurant_id'),('menu','food_id','food','food_id'),('orders','user_id','users','user_id'),('orders','restaurant_id','restaurant','restaurant_id'),('order_items','order_id','orders','order_id'),('order_items','menu_id','menu','menu_id'),('reviews','order_id','orders','order_id'),('reviews','user_id','users','user_id'),('reviews','restaurant_id','restaurant','restaurant_id')]

def validate(d):
    errors=[]
    for t in TABLES:
        if t not in d: errors.append(f'Missing table {t}'); continue
        df=d[t]; key=KEYS[t]
        if key not in df: errors.append(f'{t}: missing key {key}'); continue
        if df[key].isna().any() or df[key].duplicated().any(): errors.append(f'{t}: null or duplicate {key}')
    if errors: raise ValueError('; '.join(errors))
    for child,col,parent,pcol in FK:
        if d[child][col].isna().any() or not d[child][col].isin(d[parent][pcol]).all(): errors.append(f'Broken foreign key: {child}.{col} -> {parent}.{pcol}')
    if not d['reviews']['rating'].between(1,5).all(): errors.append('Invalid review rating')
    if not d['orders']['status'].isin(['delivered','cancelled','refunded']).all(): errors.append('Invalid order status')
    if (d['menu']['price']<=0).any() or (d['order_items']['quantity']<=0).any(): errors.append('Nonpositive price or quantity')
    if (d['orders']['order_total']<0).any(): errors.append('Negative order total')
    if not (d['order_items']['line_total']-d['order_items']['unit_price']*d['order_items']['quantity']).abs().le(.011).all(): errors.append('Order item arithmetic mismatch')
    totals=d['order_items'].groupby('order_id')['line_total'].sum()
    expected=d['orders'].set_index('order_id')['order_total']-d['orders'].set_index('order_id')['delivery_fee']
    if not (totals.reindex(expected.index)-expected).abs().le(.021).all(): errors.append('Order total reconciliation mismatch')
    if errors: raise ValueError('; '.join(errors))
    return {'status':'PASS','tables':len(TABLES),'orders':len(d['orders']),'checks':'PK, FK, domain, arithmetic, reconciliation'}

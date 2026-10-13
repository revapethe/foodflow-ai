"""Interactive read-only dashboard. Run: streamlit run app.py"""
import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st
from src.config import DB
st.set_page_config(page_title='FoodFlow AI | Analytics',page_icon='🍜',layout='wide')
st.title('🍜 FoodFlow AI — Delivery Analytics')
st.caption('Synthetic data · Local SQLite warehouse · ETL with automated validation')
if not DB.exists():
    st.error('Warehouse missing. Run `python -m src.pipeline all` first.'); st.stop()
@st.cache_data

def query(sql):
    with sqlite3.connect(DB) as con: return pd.read_sql_query(sql,con)
restaurants=query('SELECT * FROM mart_restaurant_performance')
cities=['All']+sorted(restaurants.city.unique().tolist())
city=st.sidebar.selectbox('City',cities)
filtered=restaurants if city=='All' else restaurants[restaurants.city==city]
orders=query('SELECT o.*,r.city FROM fact_orders o JOIN dim_restaurant r ON o.restaurant_key=r.restaurant_key')
orders=orders if city=='All' else orders[orders.city==city]
delivered=orders[orders.status=='delivered']
ratings=query('SELECT v.rating,r.city FROM fact_reviews v JOIN dim_restaurant r ON v.restaurant_key=r.restaurant_key')
ratings=ratings if city=='All' else ratings[ratings.city==city]
a,b,c,d=st.columns(4)
a.metric('Delivered orders',f'{len(delivered):,}')
b.metric('Revenue',f'${delivered.order_total.sum():,.2f}')
c.metric('Avg order value',f'${delivered.order_total.mean():,.2f}' if len(delivered) else '$0.00')
d.metric('Average rating',f'{ratings.rating.mean():.2f} / 5' if len(ratings) else 'N/A')
st.subheader('Revenue over time')
trend=delivered.groupby('order_date',as_index=False)['order_total'].sum()
st.plotly_chart(px.line(trend,x='order_date',y='order_total',labels={'order_total':'Revenue ($)','order_date':'Date'}),use_container_width=True)
left,right=st.columns(2)
with left:
    st.subheader('Top restaurants')
    top=filtered.sort_values('revenue',ascending=False).head(10)
    st.plotly_chart(px.bar(top,x='revenue',y='restaurant_name',orientation='h',labels={'revenue':'Revenue ($)','restaurant_name':'Restaurant'}),use_container_width=True)
with right:
    st.subheader('Order status')
    counts=orders.status.value_counts().reset_index();counts.columns=['status','count']
    st.plotly_chart(px.pie(counts,names='status',values='count'),use_container_width=True)
st.subheader('Restaurant performance')
st.dataframe(filtered.sort_values('revenue',ascending=False),use_container_width=True,hide_index=True)
st.caption('AI-ready extension: add natural-language SQL with explicit query validation. No AI API or LLM is included in this offline build.')

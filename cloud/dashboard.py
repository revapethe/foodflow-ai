"""FoodFlow Studio: Snowflake-powered interactive executive dashboard."""
import json
import os
import re
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="FoodFlow Studio", page_icon="🍜", layout="wide", initial_sidebar_state="expanded")

st.markdown('''<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Outfit:wght@400;600;700;800&display=swap');
html,body,[class*="css"], [data-testid="stApp"] {font-family:'DM Sans',sans-serif;}
[data-testid="stAppViewContainer"] {background:linear-gradient(145deg,#fffafa 0%,#fff0f0 100%);color:#292024;}
[data-testid="stSidebar"] {background:#a30f23;color:#fffafa;}
[data-testid="stSidebar"] * {color:#ffffff;}
h1,h2,h3 {font-family:'Outfit',sans-serif;letter-spacing:-.03em;}
.hero {background:linear-gradient(115deg,#b5122a,#df3045 65%,#f06472);padding:30px 36px;border-radius:22px;color:white;margin-bottom:18px;box-shadow:0 12px 30px #283c7030;}
.hero h1 {color:white;margin:0;font-size:2.35rem;}.hero p {color:#fff3f3;margin:8px 0 0;}
.kpi {background:white;border:1px solid #f7d8dc;border-radius:18px;padding:19px 20px;box-shadow:0 5px 18px #8c10200b;min-height:128px;}
.kpi .label {color:#7e5d64;font-size:13px;font-weight:600;}.kpi .value {color:#a30f23;font-family:'Outfit';font-size:29px;font-weight:800;margin-top:12px;}.kpi .note {color:#96747b;font-size:12px;margin-top:5px;}
.section {font-family:'Outfit';font-weight:700;font-size:1.3rem;color:#8e1223;margin:16px 0 8px;}
[data-testid="stVerticalBlockBorderWrapper"] {background:#ffffffeb;border-radius:16px;}
[data-testid="stSidebar"] [data-testid="stRadio"] label {color:#fff!important;}
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] label:hover {background:#c8203a;border-radius:9px;}
.stButton>button[kind="primary"] {background:#c81430;color:white;border-color:#c81430;border-radius:10px;}
.stButton>button:hover {border-color:#9c1026;color:#c81430;}
[data-testid="stMetric"] {background:white;border:1px solid #f5d5da;border-radius:14px;padding:12px;}
</style>''', unsafe_allow_html=True)

@st.cache_data(ttl=300, show_spinner=False)
def query(sql: str) -> pd.DataFrame:
    from cloud.load_snowflake import connect
    with connect() as con:
        return pd.read_sql_query(sql, con)

@st.cache_data(ttl=300, show_spinner=False)
def load_data(database: str):
    prefix=f'{database}.ANALYTICS'
    return (
        query(f'SELECT METRIC,VALUE FROM {prefix}.MART_KPIS'),
        query(f'SELECT ORDER_DATE,REVENUE,DELIVERED_ORDERS,AVG_ORDER_VALUE FROM {prefix}.MART_DAILY_SALES ORDER BY ORDER_DATE'),
        query(f'SELECT RESTAURANT_NAME,CITY,CUISINE,REVENUE,DELIVERED_ORDERS,AVG_DELIVERY_MINUTES,AVG_RATING FROM {prefix}.MART_RESTAURANT_PERFORMANCE ORDER BY REVENUE DESC'),
        query(f'SELECT FOOD_NAME,CATEGORY,ITEM_REVENUE,UNITS_SOLD FROM {prefix}.MART_TOP_FOODS ORDER BY ITEM_REVENUE DESC'),
    )

def chart_style(fig, height=360):
    fig.update_layout(height=height,margin=dict(l=8,r=8,t=22,b=8),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',font=dict(family='DM Sans',color='#704b53'),legend_title_text='',hovermode='x unified')
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor='#f7e2e5',zeroline=False)
    return fig

def metric(label, value, note):
    st.markdown(f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div><div class="note">{note}</div></div>',unsafe_allow_html=True)

st.sidebar.markdown('## 🍜 FoodFlow Studio')
st.sidebar.caption('CLOUD INTELLIGENCE / V1.0')
st.sidebar.divider()
page=st.sidebar.radio('Workspace', ['📊 Overview','🏪 Restaurants','🍱 Menu intelligence','✨ AI analyst','💬 Review intelligence','🧠 Ask in English'],label_visibility='collapsed')
st.sidebar.divider()
st.sidebar.caption('DATA SOURCE  ·  SNOWFLAKE')
raw_db=os.getenv('SNOWFLAKE_DATABASE','')
if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',raw_db):
    st.error('Set a valid SNOWFLAKE_DATABASE in .env before launching the cloud dashboard.')
    st.stop()
try:
    with st.spinner('Connecting to Snowflake analytics marts...'):
        kpis,sales,restaurants,foods=load_data(raw_db)
except Exception as exc:
    st.error('Could not load Snowflake analytics. Verify credentials, run the cloud loader, then dbt build.')
    with st.expander('Technical details'): st.exception(exc)
    st.stop()

sales['ORDER_DATE']=pd.to_datetime(sales['ORDER_DATE'],errors='coerce')
for frame,cols in [(sales,['REVENUE','DELIVERED_ORDERS','AVG_ORDER_VALUE']),(restaurants,['REVENUE','DELIVERED_ORDERS','AVG_DELIVERY_MINUTES','AVG_RATING']),(foods,['ITEM_REVENUE','UNITS_SOLD'])]:
    for col in cols: frame[col]=pd.to_numeric(frame[col],errors='coerce').fillna(0)

st.sidebar.success('Analytics marts connected')
if not sales.empty and sales['ORDER_DATE'].notna().any():
    min_date=sales['ORDER_DATE'].min().date();max_date=sales['ORDER_DATE'].max().date()
    dates=st.sidebar.date_input('Date range',(min_date,max_date),min_value=min_date,max_value=max_date)
    if isinstance(dates,(tuple,list)) and len(dates)==2:
        start,end=dates
    else: start,end=min_date,max_date
else: start=end=date.today()
city_options=sorted(restaurants['CITY'].dropna().astype(str).unique().tolist())
cities=st.sidebar.multiselect('Restaurant cities',city_options,default=city_options)
st.sidebar.caption('Date filtering applies to daily revenue; city filtering applies to restaurant analytics. The food leaderboard is all-time across cities.')
if st.sidebar.button('↻ Refresh warehouse data',use_container_width=True):
    query.clear();load_data.clear();st.rerun()

sales_view=sales[(sales['ORDER_DATE'].dt.date>=start)&(sales['ORDER_DATE'].dt.date<=end)].copy()
rest_view=restaurants[restaurants['CITY'].isin(cities)].copy()

st.markdown('<div class="hero"><h1>FoodFlow Intelligence ✦</h1><p>Restaurant growth, delivery performance and food trends — in one command center.</p></div>',unsafe_allow_html=True)

if page=='📊 Overview':
    revenue=float(sales_view['REVENUE'].sum());orders=int(sales_view['DELIVERED_ORDERS'].sum());aov=revenue/orders if orders else 0
    avg_delivery=(rest_view['AVG_DELIVERY_MINUTES']*rest_view['DELIVERED_ORDERS']).sum()/rest_view['DELIVERED_ORDERS'].sum() if rest_view['DELIVERED_ORDERS'].sum() else 0
    a,b,c,d=st.columns(4)
    with a:metric('Revenue · selected dates',f'${revenue:,.0f}','Delivered orders only')
    with b:metric('Delivered orders',f'{orders:,}','Selected date range')
    with c:metric('Average order value',f'${aov:,.2f}','Revenue ÷ delivered orders')
    with d:metric('Average delivery time',f'{avg_delivery:,.1f} min','Selected cities · all dates')
    st.markdown('<div class="section">Revenue & demand</div>',unsafe_allow_html=True)
    if sales_view.empty:st.info('No daily sales in this date range.')
    else:
        fig=px.area(sales_view,x='ORDER_DATE',y='REVENUE',color_discrete_sequence=['#c81430'],labels={'ORDER_DATE':'Date','REVENUE':'Revenue ($)'})
        fig.update_traces(line_width=3,fillcolor='rgba(89,104,217,.13)')
        st.plotly_chart(chart_style(fig),use_container_width=True)
    left,right=st.columns(2)
    with left:
        st.markdown('<div class="section">Top restaurants</div>',unsafe_allow_html=True)
        top=rest_view.nlargest(8,'REVENUE').sort_values('REVENUE')
        if top.empty:st.info('No restaurants match your filters.')
        else:
            fig=px.bar(top,x='REVENUE',y='RESTAURANT_NAME',orientation='h',color_discrete_sequence=['#dc3048'],labels={'REVENUE':'Revenue ($)','RESTAURANT_NAME':''})
            st.plotly_chart(chart_style(fig),use_container_width=True)
    with right:
        st.markdown('<div class="section">Most valuable menu items</div>',unsafe_allow_html=True)
        top=foods.nlargest(8,'ITEM_REVENUE').sort_values('ITEM_REVENUE')
        if top.empty:st.info('No food records available.')
        else:
            fig=px.bar(top,x='ITEM_REVENUE',y='FOOD_NAME',orientation='h',color_discrete_sequence=['#ff8492'],labels={'ITEM_REVENUE':'Revenue ($)','FOOD_NAME':''})
            st.plotly_chart(chart_style(fig),use_container_width=True)

elif page=='🏪 Restaurants':
    st.markdown('<div class="section">Restaurant performance</div>',unsafe_allow_html=True)
    cuisines=sorted(rest_view['CUISINE'].dropna().astype(str).unique().tolist())
    cuisine=st.selectbox('Cuisine', ['All cuisines']+cuisines)
    data=rest_view if cuisine=='All cuisines' else rest_view[rest_view['CUISINE']==cuisine]
    if data.empty:st.info('No restaurants match your filters.')
    else:
        fig=px.scatter(data,x='DELIVERED_ORDERS',y='REVENUE',size='DELIVERED_ORDERS',color='CITY',hover_name='RESTAURANT_NAME',hover_data=['CUISINE','AVG_RATING','AVG_DELIVERY_MINUTES'],labels={'REVENUE':'Revenue ($)','DELIVERED_ORDERS':'Delivered orders'})
        st.plotly_chart(chart_style(fig,420),use_container_width=True)
        st.dataframe(data.sort_values('REVENUE',ascending=False),hide_index=True,use_container_width=True)
        st.download_button('Download restaurant report',data.to_csv(index=False).encode(),file_name='foodflow_restaurants.csv',mime='text/csv')

elif page=='🍱 Menu intelligence':
    st.markdown('<div class="section">Menu performance</div>',unsafe_allow_html=True)
    categories=sorted(foods['CATEGORY'].dropna().astype(str).unique().tolist())
    category=st.selectbox('Food category',['All categories']+categories)
    data=foods if category=='All categories' else foods[foods['CATEGORY']==category]
    if data.empty:st.info('No menu items match your selection.')
    else:
        a,b=st.columns([1,2])
        with a:
            breakdown=data.groupby('CATEGORY',as_index=False)['ITEM_REVENUE'].sum()
            fig=px.pie(breakdown,values='ITEM_REVENUE',names='CATEGORY',hole=.62,color_discrete_sequence=['#bd1730','#e8475e','#ff9ca8','#861426','#f7c4cb','#d97b88'])
            st.plotly_chart(chart_style(fig),use_container_width=True)
        with b:
            top=data.nlargest(12,'UNITS_SOLD').sort_values('UNITS_SOLD')
            fig=px.bar(top,x='UNITS_SOLD',y='FOOD_NAME',orientation='h',color_discrete_sequence=['#c81430'])
            st.plotly_chart(chart_style(fig),use_container_width=True)
        st.dataframe(data.sort_values('ITEM_REVENUE',ascending=False),hide_index=True,use_container_width=True)
        st.download_button('Download menu report',data.to_csv(index=False).encode(),file_name='foodflow_menu.csv',mime='text/csv')

elif page=='💬 Review intelligence':
    st.markdown('<div class="section">LLM Review Intelligence</div>',unsafe_allow_html=True)
    st.write('Enrich real rows from FACT_REVIEWS with sentiment, topics, summaries and actions. Processing is opt-in and incurs API usage.')
    batch=st.slider('New reviews to process',1,50,10)
    if st.button('Analyze new reviews',type='primary'):
        if not os.getenv('OPENAI_API_KEY'):
            st.warning('Configure OPENAI_API_KEY in .env first.')
        else:
            try:
                from cloud.ai.review_intelligence import enrich_reviews
                from cloud.load_snowflake import connect
                with st.spinner('Analyzing reviews...'):
                    with connect() as con:
                        count=enrich_reviews(con,raw_db,batch)
                query.clear()
                st.success(f'Enriched {count} new reviews.')
            except Exception as exc:
                st.error(f'Review enrichment failed: {exc}')
    try:
        insights=query(f'''SELECT SENTIMENT, COUNT(*) AS REVIEW_COUNT
          FROM {raw_db}.ANALYTICS.AI_REVIEW_INSIGHTS GROUP BY SENTIMENT ORDER BY REVIEW_COUNT DESC''')
        if not insights.empty:
            st.plotly_chart(chart_style(px.bar(insights,x='SENTIMENT',y='REVIEW_COUNT',color='SENTIMENT',
                color_discrete_sequence=['#b5122a','#df3045','#f06472','#ffb5bf'])),use_container_width=True)
            details=query(f'''SELECT REVIEW_ID,SENTIMENT,SUMMARY,SUGGESTED_ACTION
              FROM {raw_db}.ANALYTICS.AI_REVIEW_INSIGHTS ORDER BY REVIEW_ID DESC LIMIT 100''')
            st.dataframe(details,hide_index=True,use_container_width=True)
        else: st.info('No enriched reviews yet.')
    except Exception:
        st.info('No review insights table yet. Click Analyze new reviews to create it.')

elif page=='🧠 Ask in English':
    st.markdown('<div class="section">Ask your warehouse in English</div>',unsafe_allow_html=True)
    st.write('Generate and run read-only SQL against approved Snowflake analytics tables.')
    st.warning('Use a dedicated SELECT-only Snowflake role. Do not use ACCOUNTADMIN for this feature.')
    question=st.text_input('Business question',placeholder='Which five restaurants have the highest revenue?')
    if st.button('Generate and run SQL',type='primary'):
        if not os.getenv('OPENAI_API_KEY'):st.warning('Configure OPENAI_API_KEY in .env first.')
        else:
            try:
                from cloud.ai.nl_to_sql import generate_sql,execute_readonly
                from cloud.load_snowflake import connect
                with st.spinner('Generating and validating SQL...'):
                    generated=generate_sql(question)
                    with connect() as con:
                        safe_sql,columns,rows=execute_readonly(con,generated,raw_db)
                st.code(safe_sql,language='sql')
                st.dataframe(pd.DataFrame(rows,columns=columns),hide_index=True,use_container_width=True)
            except Exception as exc:st.error(f'Unable to execute question: {exc}')

else:
    st.markdown('<div class="section">AI business analyst</div>',unsafe_allow_html=True)
    st.write('Generate grounded recommendations from **aggregate** restaurant, sales and food performance. No individual customer records are sent.')
    prompt=st.text_area('What would you like to analyze?',value='Identify the most important growth opportunities and operational risks. Provide three prioritized actions.',height=105)
    if st.button('✨ Generate executive insights',type='primary'):
        if not os.getenv('OPENAI_API_KEY'):st.warning('Add OPENAI_API_KEY to your local .env file to enable AI analysis.')
        else:
            context={'selected_period':[str(start),str(end)],'revenue':float(sales_view['REVENUE'].sum()),'delivered_orders':int(sales_view['DELIVERED_ORDERS'].sum()),'top_restaurants':rest_view.nlargest(8,'REVENUE').fillna(0).to_dict('records'),'top_foods':foods.nlargest(8,'ITEM_REVENUE').fillna(0).to_dict('records')}
            try:
                from openai import OpenAI
                with st.spinner('Preparing insights...'):
                    result=OpenAI().chat.completions.create(model=os.getenv('OPENAI_MODEL','gpt-4o-mini'),messages=[{'role':'system','content':'You are a precise food-delivery analytics advisor. Use ONLY the provided aggregate data. Clearly distinguish observations from hypotheses. Never invent numbers or causal explanations.'},{'role':'user','content':f'Question: {prompt}\nData: {json.dumps(context,default=str)}'}],max_tokens=750)
                st.markdown(result.choices[0].message.content or 'No response generated.')
            except Exception as exc:st.error(f'AI analysis failed: {exc}')

st.divider()
st.caption('FoodFlow Studio · Synthetic demo data · Cloud data pipeline: S3 → Snowflake → dbt · Built with Streamlit + Plotly')

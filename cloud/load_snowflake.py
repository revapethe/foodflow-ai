"""Load seven S3 CSVs into Snowflake RAW via a storage integration."""
import os,re
import snowflake.connector
from cloud.config import required
from src.config import TABLES

COLUMNS={
'users':'user_id NUMBER, user_name VARCHAR, city VARCHAR, signup_date DATE',
'restaurant':'restaurant_id NUMBER, restaurant_name VARCHAR, city VARCHAR, cuisine VARCHAR',
'food':'food_id NUMBER, food_name VARCHAR, category VARCHAR',
'menu':'menu_id NUMBER, restaurant_id NUMBER, food_id NUMBER, price FLOAT',
'orders':'order_id NUMBER, user_id NUMBER, restaurant_id NUMBER, ordered_at TIMESTAMP_NTZ, status VARCHAR, payment_method VARCHAR, delivery_minutes NUMBER, delivery_fee FLOAT, order_total FLOAT',
'order_items':'order_item_id NUMBER, order_id NUMBER, menu_id NUMBER, quantity NUMBER, unit_price FLOAT, line_total FLOAT',
'reviews':'review_id NUMBER, order_id NUMBER, user_id NUMBER, restaurant_id NUMBER, rating NUMBER, review_text VARCHAR'
}
def identifier(value):
 if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',value):raise ValueError(f'Invalid SQL identifier: {value}')
 return value.upper()
def connect():
 return snowflake.connector.connect(account=required('SNOWFLAKE_ACCOUNT'),user=required('SNOWFLAKE_USER'),password=required('SNOWFLAKE_PASSWORD'),role=os.getenv('SNOWFLAKE_ROLE','ACCOUNTADMIN'),warehouse=required('SNOWFLAKE_WAREHOUSE'))
def load():
 db=identifier(required('SNOWFLAKE_DATABASE'));schema=identifier(os.getenv('SNOWFLAKE_SCHEMA','RAW'))
 integration=identifier(required('SNOWFLAKE_STORAGE_INTEGRATION'))
 bucket=required('S3_BUCKET');prefix=required('S3_PREFIX').strip('/')
 if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*',bucket):raise ValueError('Invalid bucket name')
 if not re.fullmatch(r'[A-Za-z0-9_./-]+',prefix):raise ValueError('Invalid prefix')
 with connect() as con:
  cur=con.cursor()
  try:
   cur.execute(f'CREATE DATABASE IF NOT EXISTS {db}')
   cur.execute(f'CREATE SCHEMA IF NOT EXISTS {db}.{schema}')
   cur.execute(f"CREATE FILE FORMAT IF NOT EXISTS {db}.{schema}.CSV_FORMAT TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='\"' NULL_IF=('','NULL')")
   cur.execute(f"CREATE STAGE IF NOT EXISTS {db}.{schema}.FOODFLOW_STAGE URL='s3://{bucket}/{prefix}/' STORAGE_INTEGRATION={integration} FILE_FORMAT={db}.{schema}.CSV_FORMAT")
   for table in TABLES:
    target=f'{db}.{schema}.{table.upper()}'
    cur.execute(f'CREATE TABLE IF NOT EXISTS {target} ({COLUMNS[table]})')
    cur.execute(f'TRUNCATE TABLE {target}')
    cur.execute(f"COPY INTO {target} FROM @{db}.{schema}.FOODFLOW_STAGE/{table}.csv FILE_FORMAT=(FORMAT_NAME='{db}.{schema}.CSV_FORMAT') ON_ERROR=ABORT_STATEMENT FORCE=TRUE")
    cur.execute(f'SELECT COUNT(*) FROM {target}')
    print(table,cur.fetchone()[0])
  finally:cur.close()
if __name__=='__main__':load()

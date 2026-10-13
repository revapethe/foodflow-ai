"""Airflow DAG: daily batch pipeline. Runs inside Airflow with project mounted at /opt/airflow/foodflow."""
from datetime import datetime,timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
PROJECT='/opt/airflow/foodflow'
with DAG('foodflow_cloud_daily',start_date=datetime(2026,1,1),schedule='@daily',catchup=False,default_args={'retries':1,'retry_delay':timedelta(minutes=5)},tags=['foodflow','snowflake']) as dag:
 generate=BashOperator(task_id='generate_and_validate',bash_command=f'cd {PROJECT} && python -m src.pipeline all')
 upload=BashOperator(task_id='upload_to_s3',bash_command=f'cd {PROJECT} && python -m cloud.upload_s3')
 load=BashOperator(task_id='load_snowflake',bash_command=f'cd {PROJECT} && python -m cloud.load_snowflake')
 transform=BashOperator(task_id='dbt_build',bash_command=f'cd {PROJECT} && dbt build --profiles-dir .')
 generate >> upload >> load >> transform

"""Optional Airflow integration; not required for local CLI operation.
Place this file in AIRFLOW_HOME/dags and configure Airflow separately.
"""
from datetime import datetime
try:
    from airflow import DAG
    from airflow.operators.bash import BashOperator
except ImportError:
    DAG = None
if DAG is not None:
    # Set FOODFLOW_PROJECT_ROOT to the absolute path of this project.
    import os
    root=os.environ.get('FOODFLOW_PROJECT_ROOT','/opt/foodflow-ai')
    with DAG('foodflow_local_etl',start_date=datetime(2025,1,1),schedule='@daily',catchup=False,tags=['foodflow']) as dag:
        generate=BashOperator(task_id='generate',bash_command=f'cd "{root}" && python -m src.pipeline generate')
        build=BashOperator(task_id='build',bash_command=f'cd "{root}" && python -m src.pipeline build')
        generate >> build

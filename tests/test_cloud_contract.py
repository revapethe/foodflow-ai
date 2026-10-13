from pathlib import Path
from src.config import TABLES
from cloud.load_snowflake import identifier,COLUMNS

def test_all_seven_tables_have_cloud_schema():
 assert len(TABLES)==7
 assert set(TABLES)==set(COLUMNS)

def test_models_cover_all_sources():
 for table in TABLES:
  assert (Path('models/staging')/f'stg_{table}.sql').exists()

def test_identifier_rejects_injection():
 import pytest
 with pytest.raises(ValueError):identifier('RAW; DROP TABLE X')

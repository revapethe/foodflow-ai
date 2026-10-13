import pytest
from cloud.ai.review_intelligence import parse_review_output
from cloud.ai.nl_to_sql import validate_sql

def test_review_valid():
    assert parse_review_output('{"sentiment":"mixed","topics":["delivery_speed"],"summary":"Slow","action":"Review logistics"}')['sentiment']=='mixed'

def test_review_rejects_bad_topic():
    with pytest.raises(ValueError):parse_review_output('{"sentiment":"positive","topics":["hacked"],"summary":"x","action":"y"}')

def test_sql_select():
    q=validate_sql('SELECT RESTAURANT_NAME, REVENUE FROM MART_RESTAURANT_PERFORMANCE ORDER BY REVENUE DESC LIMIT 5','FOODFLOW')
    assert 'FOODFLOW.ANALYTICS.MART_RESTAURANT_PERFORMANCE' in q and 'LIMIT 100' in q

@pytest.mark.parametrize('sql',["DELETE FROM MART_KPIS",'SELECT * FROM MART_KPIS',
    'SELECT METRIC FROM OTHER_TABLE','SELECT METRIC FROM MART_KPIS; DROP TABLE MART_KPIS',
    'SELECT METRIC FROM OTHER_DB.ANALYTICS.MART_KPIS',
    'SELECT METRIC FROM MART_KPIS -- hello'])
def test_sql_rejects_unsafe(sql):
    with pytest.raises(ValueError):validate_sql(sql,'FOODFLOW')

def test_sql_cte():
    q=validate_sql('WITH totals AS (SELECT REVENUE FROM MART_DAILY_SALES) SELECT REVENUE FROM totals','FOODFLOW')
    assert 'WITH totals AS' in q

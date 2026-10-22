"""Fail a release unless the running web proxy reconciles with local source evidence.

No SQL received from HTTP is executed. All reconciliation SQL is application-owned.
Run inside the cloud workspace; this never deploys or modifies a database.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

if __package__:
    from .verify_phase1 import verify
else:
    from verify_phase1 import verify

ROOT = Path(__file__).resolve().parents[1]


def fetch(base, route, body=None):
    parts = urlsplit(base)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Use an HTTP(S) service URL without credentials, query or fragment')
    encoded = None if body is None else json.dumps(body).encode()
    request = Request(base.rstrip('/') + route, data=encoded, headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=20) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Response exceeds release-check limit')
        return json.loads(raw)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_metrics(result):
    evidence = result['evaluation']
    points = evidence['heldout']
    require(len(points) == evidence['test_days'] == 28, 'Missing final holdout evidence')
    require(all(math.isfinite(float(p[key])) for p in points for key in ('actual', 'prediction', 'lower', 'upper')), 'Non-finite holdout evidence')
    require(all(p['actual'] >= 0 and 0 <= p['lower'] <= p['prediction'] <= p['upper'] for p in points), 'Invalid holdout bounds')
    expected_days = [(date.fromisoformat(evidence['test_start'])+timedelta(days=i)).isoformat() for i in range(28)]
    require([p['date'] for p in points] == expected_days, 'Missing or duplicate holdout days')
    errors = [abs(p['actual'] - p['prediction']) for p in points]
    actual_total = sum(p['actual'] for p in points)
    computed = {'mae': sum(errors)/len(errors), 'rmse': math.sqrt(sum(e*e for e in errors)/len(errors)),
                'wape_percent': sum(errors)/actual_total*100 if actual_total else None}
    recorded = evidence['candidates'][result['selected_model']]['test']
    for key, value in computed.items():
        require(recorded[key] is None if value is None else math.isclose(value, recorded[key], abs_tol=1e-6), f'Incorrect heldout {key}')
    coverage = sum(p['lower'] <= p['actual'] <= p['upper'] for p in points)/28*100
    require(math.isclose(coverage, evidence['test_band_coverage_percent'], abs_tol=1e-6), 'Incorrect heldout band coverage')
    require(all(f['train_end'] < f['validation_start'] <= f['validation_end'] for f in evidence['folds']), 'Validation observes future data')
    selected_validation = evidence['candidates'][result['selected_model']]['validation']['mae']
    require(selected_validation <= min(c['validation']['mae'] for c in evidence['candidates'].values())+1e-6, 'Selection ignores validation error')
    require(evidence['folds'][-1]['validation_end'] < evidence['calibration_start'] <= evidence['calibration_end'] < evidence['test_start'], 'Chronological split leakage')
    require(points[0]['date'] == evidence['test_start'] and points[-1]['date'] == evidence['test_end'] == result['as_of'], 'Inconsistent holdout dates')
    require(len(result['predictions']) == result['horizon_days'] == 14, 'Missing forecast horizon')
    expected_future = [(date.fromisoformat(result['as_of'])+timedelta(days=i+1)).isoformat() for i in range(14)]
    require([p['date'] for p in result['predictions']] == expected_future, 'Missing or duplicate forecast days')
    require(all(p['date'] > result['as_of'] and 0 <= p['lower'] <= p['prediction'] <= p['upper'] for p in result['predictions']), 'Invalid future forecast bounds')
    return {key: recorded[key] for key in computed}


def check(base, path, artifact_path, expected_revision=None):
    require(fetch(base, '/api/health') == {'status': 'ok'}, 'Service is not healthy')
    version = fetch(base, '/api/version')
    require(version['application'] == 'FoodFlow Intelligence', 'Unexpected application')
    if expected_revision:
        require(version['release_revision'] == expected_revision, 'Deployed revision differs from reviewed commit')
    verify(base, path)
    artifact = json.loads(Path(artifact_path).read_text())
    forecasts = []
    for suffix, key in [('', '__all__'), ('?city=Denver', 'Denver')]:
        result = fetch(base, '/api/intelligence' + suffix)
        require(result['status'] == 'ready', 'Forecast evidence unavailable or stale')
        reference = artifact['markets'][key]
        require(result['input_fingerprint'] == artifact['input_fingerprint'], 'Warehouse/model fingerprint mismatch')
        for field in ('selected_model', 'as_of', 'predictions', 'evaluation'):
            require(result[field] == reference[field], f'Forecast evidence differs: {field}')
        forecasts.append({'market': key, 'selected_model': result['selected_model'], 'holdout': check_metrics(result)})
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        cases = [('What is total revenue?', {}, None, None, None),
                 ('How many orders?', {'city': 'Denver'}, 'Denver', None, None),
                 ('Revenue in Denver from 2025-03-01 to 2025-06-30', {'city': 'Boston'}, 'Denver', '2025-03-01', '2025-06-30')]
        for question, filters, city, start, end in cases:
            result = fetch(base, '/api/assistant', {'question': question, **filters})
            require(result['status'] == 'answered', 'Assistant did not answer a supported question')
            conditions, params = ['1=1'], []
            for clause, value in [('r.city=?', city), ('o.order_date>=?', start), ('o.order_date<=?', end)]:
                if value is not None:
                    conditions.append(clause); params.append(value)
            row = db.execute('''SELECT COUNT(*) AS all_orders,
                COUNT(CASE WHEN o.status='delivered' THEN 1 END) AS delivered_orders,
                ROUND(COALESCE(SUM(CASE WHEN o.status='delivered' THEN o.order_total ELSE 0 END),0),2) AS delivered_revenue
                FROM fact_orders o JOIN dim_restaurant r ON r.restaurant_key=o.restaurant_key WHERE ''' + ' AND '.join(conditions), params).fetchone()
            require(all(result['rows'][0][key] == row[key] for key in row.keys()), 'Assistant result differs from warehouse')
            require(result['filters'] == {'city': city, 'start': start, 'end': end}, 'Assistant filter precedence differs')
            require(result['matching_orders'] == row['all_orders'], 'Assistant scope count differs')
    unknown = fetch(base, '/api/assistant', {'question': 'Why is profit falling?'})
    require(unknown['status'] == 'clarification' and 'rows' not in unknown, 'Assistant guessed an unsupported answer')
    return {'status': 'passed', 'checked_at': datetime.now(timezone.utc).isoformat(),
            'release': version, 'historical_reconciliations': 10, 'forecast_checks': forecasts,
            'assistant_reconciliations': 3, 'unsupported_question_refused': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-url', required=True)
    parser.add_argument('--db', type=Path, default=ROOT/'warehouse/foodflow.db')
    parser.add_argument('--artifact', type=Path, default=ROOT/'artifacts/intelligence.json')
    parser.add_argument('--expected-revision')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        report = check(args.web_url, args.db, args.artifact, args.expected_revision)
    except Exception as exc:
        report = {'status': 'failed', 'error_type': type(exc).__name__}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2)+'\n')
        raise
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()

"""Read-only independent ledger/return/packet reconciliation; never writes storage.

Run with --start/--end. Only the local JSON audit artifact is written. Source
credentials and raw account/task records are deliberately omitted from output.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from hashlib import sha256
from math import isclose
from pathlib import Path

from pymongo import MongoClient, ReadPreference

from slicing_dashboard.config import get_settings, PROJECT_ROOT
from slicing_dashboard.processing.batch_ratios import batch_ratios
from slicing_dashboard.processing.daily_work import EXCLUDED, INDIA, instant
from slicing_dashboard.reporting.approval_funnel import cohort_records, prepare_funnel, STAGES
from slicing_dashboard.reporting.rework_tiers import rework_hours, TIERS
from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart


def reconcile(batches, returns, mapping, start, end, reviews=()):
    def resolve(batch):
        return mapping.get(str(batch.get('assignee_id')), mapping.get(batch.get('username'),
                           batch.get('canonical_user') or batch.get('username')))

    identities = [str(batch['batch_id']) for batch in batches]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate batch ledger identities')
    events = defaultdict(set)
    active = set()
    physical = Counter()
    for row in returns:
        stamp = instant(row.get('returned_at'))
        if stamp is None or stamp.date().isoformat() > end:
            continue
        batch = row.get('batch_id')
        identity = row.get('event_id') or (batch, stamp.isoformat(), row.get('user_id'))
        events[batch].add(identity)
        physical[batch] += 1
        if start <= stamp.date().isoformat():
            active.add(batch)
    # Independent direct-record loops, separate from batch_ratios/rework_hours.
    seconds = defaultdict(float)
    counts = Counter()
    completed = pending = 0.
    eligible_ids = set()
    ledger_mismatches = []
    for batch in batches:
        identifier = batch['batch_id']
        status = batch.get('status')
        if not (start <= str(batch.get('batch_date') or '') <= end or identifier in active):
            continue
        submitted = status in {'batch_completed', 'batch_rework', 'batch_reviewing',
            'batch_pending_leader_review', 'batch_pending_auditor_review', 'batch_pending_admin_review'}
        submitted |= any(float(batch.get(field) or 0) > 0 for field in
                         ('completed_count', 'pending_review_count', 'return_count', 'rework_count'))
        if not (submitted or identifier in active) or resolve(batch) in EXCLUDED:
            continue
        duration = float(batch['total_duration_seconds'])
        tier = TIERS[min(3, len(events[identifier]))]
        counts[tier] += 1
        seconds[tier] += duration
        eligible_ids.add(identifier)
        if status == 'batch_completed':
            completed += duration
        else:
            pending += duration
        if int(batch.get('return_count') or 0) != len(events[identifier]):
            ledger_mismatches.append({'batch_id': identifier,
                                     'ledger_returns': batch.get('return_count'),
                                     'recorded_returns': len(events[identifier])})
    frame = batch_ratios(batches, returns, start, end, resolve)
    chart_tiers = rework_hours(frame)
    checks = {tier: isclose((chart_tiers[tier] or 0) * 3600, seconds[tier], abs_tol=1e-5)
              for tier in TIERS}
    views = {}
    for state, expected in [('All', completed + pending), ('Completed', completed), ('Pending approvals', pending)]:
        figure = build_rework_ratio_chart(frame, start, True, completion_state=state)
        total = sum(figure.layout.meta['column_totals']) * 3600 if figure.data else 0
        views[state] = {'source_seconds': expected, 'total_row_seconds': total,
                        'match': isclose(expected, total, abs_tol=1e-5)}
    cohort = cohort_records(reviews, batches, resolve)
    dates = sorted({str(batch.get('batch_date')) for batch in batches
                    if start <= str(batch.get('batch_date') or '') <= end})
    _, totals = prepare_funnel(cohort, dates)
    # Independent source interpretation: maintain the set of prerequisites that
    # passed in the latest review cycle, then apply newer observed ledger status.
    histories = defaultdict(list)
    for event in reviews:
        if event.get('active') and not event.get('is_synthetic') and event.get('source') == 'batch-review':
            histories[str(event.get('batch_id'))].append(event)
    passed = {}
    for batch in batches:
        identifier = str(batch['batch_id'])
        history = sorted(histories[identifier], key=lambda row: (row.get('event_at') or '', row.get('id') or ''))
        approvals, rejected, new_cycle = set(), None, False
        for event in history:
            if event.get('stage') not in STAGES:
                continue
            index = STAGES.index(event['stage'])
            if event.get('action') == 'Returned for Rework':
                approvals, rejected, new_cycle = set(STAGES[:index]), index, True
            elif event.get('action') == 'Approved':
                if new_cycle:
                    approvals = set()
                approvals.update(STAGES[:index + 1])
                rejected, new_cycle = None, False
        ledger = datetime.fromisoformat(str(batch['last_updated']).replace('Z', '+00:00')) if batch.get('last_updated') else None
        if ledger and ledger.tzinfo is None:
            ledger = ledger.replace(tzinfo=INDIA)
        last_review = instant(history[-1].get('event_at')) if history else None
        if last_review is None or (ledger and ledger >= last_review):
            levels = {'batch_completed': 3, 'batch_pending_admin_review': 2,
                      'batch_pending_auditor_review': 1}
            status = batch.get('status')
            approvals = set(STAGES[:levels.get(status, 0)])
            if status == 'batch_rework' and rejected is not None:
                approvals = set(STAGES[:rejected])
        passed[identifier] = approvals
    stages = {}
    for stage in STAGES:
        rows = [batch for batch in batches if start <= str(batch.get('batch_date') or '') <= end
                and resolve(batch) not in EXCLUDED and stage in passed[str(batch['batch_id'])]]
        expected = sum(float(row['total_duration_seconds']) for row in rows)
        actual = totals[stage]['Approved']
        stages[stage] = {'ledger_seconds': expected, 'ledger_batches': len(rows),
                         'match': actual['count'] == len(rows) and isclose(actual['seconds'], expected)}
    return {'range': [start, end], 'batch_records_read': len(batches),
            'return_documents_read': len(returns), 'eligible_batches': len(eligible_ids),
            'duplicate_return_documents_through_end': sum(physical.values()) - sum(map(len, events.values())),
            'tiers': {tier: {'seconds': seconds[tier], 'batches': counts[tier], 'match': checks[tier]} for tier in TIERS},
            'legacy_inventory_views': views, 'inventory_approval_cohort': stages, 'review_records_read': len(reviews),
            'ledger_return_discrepancies': ledger_mismatches,
            'all_reconciled': all(checks.values()) and all(row['match'] for row in views.values())
                              and all(row['match'] for row in stages.values())}


def native_period_check(settings, mapping, start, end):
    """Independent native period metric, account rows, heatmap and Admin parity."""
    import pandas as pd
    from slicing_dashboard.scraper.http_scraper import HTTPScraper
    from slicing_dashboard.plots.period_rework import build_period_rework
    from slicing_dashboard.plots.overview_charts import build_approval_progression
    from slicing_dashboard.plots.theme import format_seconds
    scraper = HTTPScraper(settings)
    try:
        if not scraper.login():
            raise ConnectionError('Period source login failed')
        response = scraper._client.get(scraper._base_url + '/api/dashboard/overview',
            params={'mode': 'slice', 'start_date': start, 'end_date': end}, timeout=15)
        response.raise_for_status()
        overview = response.json()
        if (overview.get('range', {}).get('start_date'), overview.get('range', {}).get('end_date')) != (start, end):
            raise ValueError('Native overview period mismatch')
        source_seconds = float(overview['metrics']['slice_period_completed_duration_seconds'])
        totals, identities = {}, set()
        for page in range(1, 101):
            response = scraper._client.get(scraper._base_url + '/api/dashboard/annotator-efficiency',
                params={'start_date': start, 'end_date': end, 'role': 2, 'page': page, 'page_size': 200}, timeout=15)
            response.raise_for_status()
            payload = response.json()
            if payload.get('date_range') != {'start_date': start, 'end_date': end}:
                raise ValueError('Native account period mismatch')
            for row in payload['items']:
                identity = str(row['user_id'])
                if identity in identities:
                    raise ValueError('Duplicate period account')
                identities.add(identity)
                user = mapping.get(identity, mapping.get(row['username'], row['username']))
                if user in EXCLUDED:
                    continue
                total = totals.setdefault(user, {'User': user, 'seconds': 0., 'tasks': 0})
                total['seconds'] += float(row['completed_duration_seconds'])
                total['tasks'] += int(row['completed_count'])
            if len(identities) == payload['total']:
                break
            if not payload['items'] or len(identities) > payload['total']:
                raise ValueError('Incomplete period accounts')
        else:
            raise ValueError('Period pagination limit reached')
        completion = {'available': True, 'rows': list(totals.values())}
        chart = build_period_rework(pd.DataFrame(), completion, 'Completed', True)
        pyramid = build_approval_progression({}, [start, end], completion=completion)
        heatmap_seconds = chart.layout.meta['column_totals'][-1] * 3600
        admin_seconds = pyramid.data[0].x[-1] * 3600
        account_seconds = sum(row['seconds'] for row in totals.values())
        return {'range': [start, end], 'native_period_seconds': source_seconds,
                'native_account_seconds': account_seconds, 'heatmap_seconds': heatmap_seconds,
                'admin_completed_seconds': admin_seconds, 'duration': format_seconds(account_seconds),
                'completed_tasks': sum(row['tasks'] for row in totals.values()),
                'completed_batch_count': None, 'completed_return_tier_split': 'Unavailable: no dated batch completion evidence',
                'totals_excluded_from_color_scale': len(chart.data) == 2 and
                    chart.data[0].zmax == max(value for row in chart.data[0].z for value in row if value is not None),
                'match': all(isclose(value, source_seconds, abs_tol=.02) for value in
                             (account_seconds, heatmap_seconds, admin_seconds))}
    finally:
        scraper._client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    args = parser.parse_args()
    settings = get_settings()
    client = None
    report = {'verified_at': datetime.now(timezone.utc).isoformat()}
    try:
        client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000, timeoutMS=15000, socketTimeoutMS=15000,
            read_preference=ReadPreference.NEAREST)
        database = client['slicing_dashboard']
        batches = list(database.batches_master.find({}, {'_id': 0}).max_time_ms(10000))
        returns = list(database.batch_returns.find({}, {'_id': 0}).max_time_ms(10000))
        mappings = list(database.user_mappings.find({}, {'_id': 0}).max_time_ms(10000))
        mapping = {str(row['id']): row['mapped_user'] for row in mappings if row.get('mapped_user')}
        instance = sha256(settings.dashboard_url.rstrip('/').encode()).hexdigest()[:16]
        prefix = instance + ':batch-review:'
        reviews = [json.loads(row['payload']) for row in database.workflow_records.find(
            {'kind': 'event', '_id': {'$gte': prefix, '$lt': prefix + '\uffff'}}, {'payload': 1}).max_time_ms(10000)]
        report.update(reconcile(batches, returns, mapping, args.start, args.end, reviews))
        report['period_completion'] = native_period_check(settings, mapping, args.start, args.end)
        report['all_reconciled'] &= report['period_completion']['match']
        report['source'] = 'MongoDB batches_master, batch_returns, user_mappings, workflow_records (read only)'
    except Exception as error:
        report.update(available=False, error_type=type(error).__name__)
    finally:
        if client is not None:
            client.close()
    target = PROJECT_ROOT / 'data/reports/chart-qa/dashboard-consistency.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    if report.get('available') is False or not report.get('all_reconciled'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

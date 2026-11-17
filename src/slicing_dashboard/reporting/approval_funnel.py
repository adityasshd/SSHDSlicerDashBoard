"""Latest outcomes for one batch cohort, with nested approval prerequisites."""
from collections import defaultdict
from datetime import datetime
import math

from slicing_dashboard.processing.daily_work import EXCLUDED, INDIA, instant

STAGES = ('Leader', 'Auditor', 'Admin')
PASSED = {'batch_pending_auditor_review': 0, 'batch_pending_admin_review': 1,
          'batch_completed': 2}
QUEUES = {'batch_reviewing': 0, 'batch_pending_leader_review': 0,
          'batch_pending_auditor_review': 1, 'batch_pending_admin_review': 2}


def cohort_records(events, batches, resolve, covered_dates=()):
    """Count each identified batch once; review dates never move its cohort.

    A downstream pass establishes upstream passes for the same batch. A return
    preserves its earlier prerequisites until a new review cycle starts.
    Current batch status wins over an older review observation.
    """
    by_batch = defaultdict(list)
    for event in events:
        if (event.get('source') == 'batch-review' and event.get('active')
                and not event.get('is_synthetic') and event.get('stage') in STAGES):
            by_batch[str(event.get('batch_id'))].append(event)
    rows, seen = [], set()
    for batch in batches:
        identifier = str(batch.get('batch_id') or '')
        if not identifier or identifier in seen:
            raise ValueError('Missing or duplicate batch identity')
        seen.add(identifier)
        member = resolve(batch)
        if not member or member in EXCLUDED:
            continue
        status = batch.get('status')
        history = sorted(by_batch[identifier], key=lambda e: (e.get('event_at') or '', e.get('id') or ''))
        highest, rejected, returned = -1, None, False
        for event in history:
            stage = STAGES.index(event['stage'])
            if event.get('action') == 'Returned for Rework':
                highest, rejected, returned = stage - 1, stage, True
            elif event.get('action') == 'Approved':
                if returned:
                    highest, rejected, returned = -1, None, False
                highest = max(highest, stage)
        latest = history[-1] if history else {}
        ledger_value = batch.get('last_updated')
        # The retained batch ledger used local India wall time, while source
        # review timestamps use Shanghai. Compare their actual instants.
        ledger_at = datetime.fromisoformat(str(ledger_value).replace('Z', '+00:00')) if ledger_value else None
        if ledger_at and ledger_at.tzinfo is None:
            ledger_at = ledger_at.replace(tzinfo=INDIA)
        event_at = instant(latest.get('event_at'))
        current = not event_at or (ledger_at and ledger_at >= event_at)
        if current:
            if status in PASSED:
                highest, rejected = PASSED[status], None
            elif status in QUEUES:
                highest, rejected = QUEUES[status] - 1, None
            elif status == 'batch_rework':
                highest = rejected - 1 if rejected is not None else -1
            else:
                highest, rejected = -1, None
        outcomes = []
        for index in range(3):
            if current and status == 'batch_rework' and rejected is None:
                outcome = 'Unknown'
            elif index <= highest:
                outcome = 'Approved'
            elif index == rejected:
                outcome = 'Rejected / returned'
            elif rejected is not None or index > highest + 1:
                outcome = 'Not reached'
            elif status == 'batch_rework' and rejected is None:
                outcome = 'Unknown'
            elif status in ('batch_unassigned', 'batch_member_assigned', 'batch_assigned', 'batch_pending_assignment'):
                outcome = 'Not reached'
            elif status in QUEUES or latest.get('action') == 'Approved':
                outcome = 'Awaiting review'
            else:
                outcome = 'Unknown'
            outcomes.append(outcome)
        try:
            seconds = float(batch.get('total_duration_seconds'))
            if not math.isfinite(seconds) or seconds < 0:
                seconds = None
        except (ValueError, TypeError):
            seconds = None
        rows.append({'batch_id': identifier, 'date': batch.get('batch_date'), 'member': member,
                     'seconds': seconds, 'outcomes': outcomes,
                     'unresolved_return': bool(current and status == 'batch_rework' and rejected is None)})
    return {'rows': rows, 'covered_dates': sorted(set(covered_dates)), 'basis': 'batch_date'}


def prepare_funnel(payload, dates, selected=None):
    selected = set(selected) if selected else None
    covered = set(payload.get('covered_dates', []))
    daily = {day: {'date': day, **{stage.lower() + '_seconds': 0. if day in covered else None
                                 for stage in STAGES}} for day in dates}
    totals = {stage: {outcome: {'seconds': 0., 'count': 0, 'missing': 0} for outcome in
                      ('Approved', 'Rejected / returned', 'Awaiting review', 'Not reached', 'Unknown')}
              for stage in STAGES}
    for batch in payload.get('rows', []):
        if batch['date'] not in daily or (selected and batch['member'] not in selected):
            continue
        # One common duration per batch ensures Admin <= Auditor <= Leader.
        # Missing durations leave the whole cohort date unknown at every stage.
        if batch['seconds'] is None or 'Unknown' in batch['outcomes']:
            for stage in STAGES:
                daily[batch['date']][stage.lower() + '_seconds'] = None
        for stage, outcome in zip(STAGES, batch['outcomes']):
            total = totals[stage][outcome]
            total['count'] += 1
            if batch['seconds'] is None:
                total['missing'] += 1
            else:
                total['seconds'] += batch['seconds']
                field = stage.lower() + '_seconds'
                if outcome == 'Approved' and daily[batch['date']][field] is not None:
                    daily[batch['date']][field] += batch['seconds']
    return list(daily.values()), totals

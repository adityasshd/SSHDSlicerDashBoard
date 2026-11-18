"""Evidence-backed submitted *video* hours, distinct from labor time.

The Daily Report's legacy "Total Duration" intentionally excludes old
rework. This projection defines the complete submitted output as the sum of
three disjoint submitted-task buckets, without changing the legacy KPI.
No batch-return event by itself proves a same-day submission.
"""
from math import isfinite
from datetime import date

from slicing_dashboard.reporting.dashboard_reports import reporting_user


BUCKETS = (
    ('new', 'New videos', 'New Videos (First Time)', 'New Tasks'),
    ('old_rework', 'Old rework', 'Old Rework', 'Old Rework Tasks'),
    ('same_day_rework', 'Same-day rework', 'Same-day Rework',
     'Same-day Rework Tasks'),
)


def submitted_video_output(day, selected_users=None, expected_date=None):
    """Produce exactly four comparable lollipop values or mark unavailable.

    Completed approvals, work-session time and original batch duration must
    never be substituted for verified task submission timestamps.
    """
    if not isinstance(day, dict):
        return {'available': False, 'reason': 'No dated submission capture'}
    actual_date = day.get('date')
    try:
        date.fromisoformat(actual_date)
    except (TypeError, ValueError):
        return {'available': False, 'reason': 'Invalid submission date'}
    if expected_date is not None and actual_date != expected_date:
        return {'available': False, 'reason': 'Saved submission date does not match today'}
    metadata = day.get('metadata') or {}
    if metadata.get('available') is not True:
        return {'available': False, 'date': actual_date,
                'reason': 'No verified task-submission evidence for this day'}
    if metadata.get('target_date') not in (None, actual_date):
        return {'available': False, 'date': actual_date,
                'reason': 'Source report belongs to a different day'}
    rows = day.get('rows')
    if not isinstance(rows, list):
        return {'available': False, 'date': actual_date,
                'reason': 'Submission rows are missing'}
    selected = set(selected_users) if selected_users is not None else None
    if selected is not None and not selected:
        return {'available': False, 'date': actual_date,
                'reason': 'No users selected'}
    sums = {key: 0.0 for key, _, _, _ in BUCKETS}
    counts = {key: 0 for key, _, _, _ in BUCKETS}
    count_known = {key: True for key, _, _, _ in BUCKETS}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            return {'available': False, 'date': actual_date,
                    'reason': 'Invalid submission row'}
        user = row.get('User')
        if not reporting_user(user):
            continue
        if user in seen:
            return {'available': False, 'date': actual_date,
                    'reason': 'Duplicate user in saved submission summary'}
        seen.add(user)
        if selected is not None and user not in selected:
            continue
        if any(field not in row or row.get(field) is None
               for _, _, field, _ in BUCKETS):
            return {'available': False, 'date': actual_date,
                    'reason': 'Missing new/old/same-day submission breakdown'}
        for key, _, duration_field, count_field in BUCKETS:
            try:
                seconds = float(row[duration_field])
                count = row.get(count_field)
                if not isfinite(seconds) or seconds < 0:
                    raise ValueError('Invalid video seconds')
                if count is not None and (type(count) not in (int, float) or
                                          not isfinite(count) or count < 0 or count != int(count)):
                    raise ValueError('Invalid task count')
            except (ValueError, TypeError, OverflowError):
                return {'available': False, 'date': actual_date,
                        'reason': 'Invalid submission metric'}
            sums[key] += seconds
            if count is not None:
                counts[key] += int(count)
            else:
                count_known[key] = False
    total = sum(sums.values())
    counts = {key: value if count_known[key] else None for key, value in counts.items()}
    total_tasks = (sum(counts.values()) if all(value is not None for value in counts.values())
                   else None)
    return {
        'available': True,
        'date': actual_date,
        'source': 'dated_task_submission_capture',
        'unit': 'submitted_video_seconds',
        'values': {
            'submitted_total': total,
            **sums,
        },
        'counts': {
            'submitted_total': total_tasks,
            **counts,
        },
        'capture': metadata.get('captured_at'),
        'is_snapshot': bool(metadata.get('is_snapshot')),
        'reconciliation_pending': bool(metadata.get('reconciliation_pending')),
        'labor_seconds': None,
        'labor_evidence': 'No activity-session timing source verified',
    }


def submission_rework_counts(day, selected_users=None, expected_date=None):
    """Two verified *task submission* counts for the today chart.

    Rework is a subset of submitted tasks (old + same-day), NOT the number
    of recorded batch-return notices. Video seconds and worklog time are not
    needed to calculate these counts. A missing dated Daily capture or missing
    per-task bucket counts cannot be represented as zero.
    """
    if not isinstance(day, dict):
        return {'available': False, 'reason': 'No dated task-submission capture'}
    actual_date = day.get('date')
    try:
        date.fromisoformat(actual_date)
    except (ValueError, TypeError):
        return {'available': False, 'reason': 'Invalid task-submission date'}
    if expected_date is not None and actual_date != expected_date:
        return {'available': False, 'reason': 'Saved task submissions are not for today'}
    metadata = day.get('metadata') or {}
    if metadata.get('available') is not True:
        return {'available': False, 'date': actual_date,
                'reason': 'No verified task submissions for this date'}
    if metadata.get('target_date') not in (None, actual_date):
        return {'available': False, 'date': actual_date,
                'reason': 'Source task submissions belong to another day'}
    rows = day.get('rows')
    if not isinstance(rows, list):
        return {'available': False, 'date': actual_date,
                'reason': 'Dated submission rows are missing'}
    selected = set(selected_users) if selected_users is not None else None
    if selected is not None and not selected:
        return {'available': False, 'date': actual_date,
                'reason': 'No users selected'}

    totals = {'new': 0, 'old_rework': 0, 'same_day_rework': 0}
    fields = {key: count_field for key, _, _, count_field in BUCKETS}
    seen_users = set()
    for row in rows:
        if not isinstance(row, dict):
            return {'available': False, 'date': actual_date,
                    'reason': 'Invalid task-submission row'}
        user = row.get('User')
        if not reporting_user(user):
            continue
        if user in seen_users:
            return {'available': False, 'date': actual_date,
                    'reason': 'Duplicate user in task-submission report'}
        seen_users.add(user)
        if selected is not None and user not in selected:
            continue
        for key, field in fields.items():
            count = row.get(field)
            if (type(count) not in (int, float) or not isfinite(count) or
                    count < 0 or int(count) != count):
                return {'available': False, 'date': actual_date,
                        'reason': 'Task counts are missing or unverified'}
            totals[key] += int(count)

    rework = totals['old_rework'] + totals['same_day_rework']
    total = totals['new'] + rework
    return {
        'available': True, 'date': actual_date,
        'source': 'dated_task_submission_capture',
        'unit': 'task_submissions',
        'counts': {'submitted_total': total, 'rework_total': rework, **totals},
        'capture': metadata.get('captured_at'),
        'is_snapshot': bool(metadata.get('is_snapshot')),
        'reconciliation_pending': bool(metadata.get('reconciliation_pending')),
        'coverage': metadata.get('coverage'),
    }

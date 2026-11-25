"""Forward-only submission observations from the permitted slicer inventory.

Two successful observations bound a status transition. updated_at is used only
to reduce inventory reads, never as a submission time. Initial inventory stock,
overnight intervals and first-seen submitted tasks are deliberately not output.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import math
from zoneinfo import ZoneInfo
from time import monotonic

from slicing_dashboard.processing.daily_work import instant
from slicing_dashboard.processing.workflow_history import WorkflowStore
from slicing_dashboard.reporting.dashboard_reports import reporting_user

START_DATE = '2026-11-25'
INDIA = ZoneInfo('Asia/Kolkata')
BEFORE = {'slice_assigned', 'slicing', 'slice_rework'}
AFTER = {'slice_submitted', 'slice_pending_auditor_review',
         'slice_pending_admin_review', 'slice_reviewing', 'slice_completed'}


def tracking_instance(manager):
    scope = f'{manager.scraper._base_url.rstrip("/")}:{manager.settings.admin_username}'
    return 'submission-tracking:' + hashlib.sha256(scope.encode()).hexdigest()[:24]


def transition_plan(previous, rows, began, finished, instance):
    """Validate the complete capture before producing any durable changes."""
    first, last = instant(began), instant(finished)
    if first is None or last is None or last < first:
        raise ValueError('Invalid observation interval')
    previous = previous or {}
    if previous.get('sort_at') and instant(previous['sort_at']) >= first:
        raise ValueError('Out-of-order submission capture')
    day = last.date().isoformat()
    tasks = dict(previous.get('tasks', {}))
    events, seen = [], set()
    for row in rows:
        tid = str(row.get('id') or '')
        if not tid or tid in seen or row.get('workflow_type') != 'slice':
            raise ValueError('Invalid or duplicate submission inventory task')
        seen.add(tid)
        seconds = row.get('duration_seconds')
        if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid task video duration')
        status, uid = row.get('status'), row.get('slicer_id')
        old = tasks.get(tid)
        # Both observations must be on this India-local day. A review of an
        # already submitted task, a reassignment, or an overnight gap adds zero.
        lower = instant(old.get('observed_at')) if old else None
        if (day >= START_DATE and first.date() == last.date() and lower
                and lower.date() == last.date() and lower <= first
                and old.get('status') in BEFORE and status in AFTER
                and uid is not None and str(old.get('user_id')) == str(uid)):
            events.append({
                'id': f'{instance}:task:{day}:{tid}', 'instance': instance,
                'task_id': tid, 'user_id': uid, 'username': row.get('slicer'),
                'duration_seconds': float(seconds), 'display_date': day,
                'observed_after': old['observed_at'], 'observed_before': finished,
                'sort_at': finished, 'prior_status': old['status'], 'status': status,
                'source': '/api/slice/tasks', 'submission_timestamp': None,
            })
        tasks[tid] = {'status': status, 'user_id': uid, 'observed_at': began}
    same_day = previous.get('display_date') == day
    checkpoint = {
        'id': instance + ':checkpoint', 'instance': instance,
        'display_date': day, 'sort_at': began, 'captured_at': finished,
        'tracking_started_at': previous.get('tracking_started_at') or began,
        'coverage_since': previous.get('coverage_since') if same_day else began,
        'tasks': tasks, 'start_date': START_DATE,
        'partial': True, 'source': '/api/slice/tasks',
    }
    return checkpoint, events


def fetch_inventory(manager, previous=None):
    """Complete cursor scan, or a checked updated-time overlap after baseline.

    The API caps its approximate total at 10,000, but cursor pagination can
    continue beyond it. Never use that approximate total as an end condition.
    """
    if not manager.scraper.is_authenticated and not manager.scraper.login():
        raise ConnectionError('Submission tracking login failed')
    same_day = previous and previous.get('display_date') == datetime.now(INDIA).date().isoformat()
    cutoff = instant(previous['sort_at']) - timedelta(minutes=10) if same_day else None
    rows, ids, cursors = [], set(), set()
    cursor, last_stamp = None, None
    for page in range(1, 1001):
        params = {'workflow_type': 'slice', 'page_size': 200,
                  'group_id': manager.settings.efficiency_leader_id}
        if cursor:
            params['cursor'] = cursor
        response = manager.scraper._client.get(
            manager.scraper._base_url + '/api/slice/tasks', params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        batch, meta = payload.get('data'), payload.get('meta', {})
        if not isinstance(batch, list) or type(meta.get('has_more')) is not bool:
            raise ValueError('Incomplete submission inventory pagination')
        older = False
        for row in batch:
            tid = str(row.get('id') or '')
            stamp = instant(row.get('updated_at'))
            if not tid or tid in ids or stamp is None:
                raise ValueError('Invalid submission inventory boundary')
            if last_stamp is not None and stamp > last_stamp:
                raise ValueError('Submission inventory changed during pagination')
            last_stamp = stamp
            ids.add(tid)
            rows.append(row)
            older = cutoff is not None and stamp < cutoff
        if not meta['has_more'] or older:
            return rows
        next_cursor = meta.get('next_cursor')
        if not batch or not next_cursor or next_cursor in cursors:
            raise ValueError('Submission inventory did not advance')
        cursors.add(next_cursor)
        cursor = next_cursor
    raise ValueError('Submission inventory exceeded page limit')


def capture_submissions(manager, store=None):
    store = store or WorkflowStore(manager.db)
    instance = tracking_instance(manager)
    owner = hashlib.sha256(str(datetime.now(timezone.utc)).encode()).hexdigest()
    lease = instance + ':lease'
    if not store.acquire_lease(lease, owner, 600):
        raise RuntimeError('Submission tracking is already running')
    try:
        started = monotonic()
        previous = store.get(instance + ':checkpoint')
        began = datetime.now(timezone.utc).isoformat()
        rows = fetch_inventory(manager, previous)
        finished = datetime.now(timezone.utc).isoformat()
        checkpoint, events = transition_plan(previous, rows, began, finished, instance)
        if monotonic() - started > 540:
            raise TimeoutError('Submission inventory exceeded its capture lease')
        # Insert-once task/day IDs survive retries, approvals and resubmissions.
        # A failed checkpoint leaves replay safe; no status snapshot becomes work.
        store.save_many('submission-observation', events)
        if not store.save_newer(checkpoint['id'], 'submission-tracking', checkpoint):
            raise RuntimeError('Newer submission capture already published')
        return {'captured_at': finished, 'coverage_since': checkpoint['coverage_since'],
                'scanned_tasks': len(rows), 'observed_transitions': len(events)}
    finally:
        store.release_lease(lease, owner)


def saved_observed_submissions(manager, day, selected=None, store=None):
    store = store or WorkflowStore(manager.db, initialize=False).chart_reader()
    instance = tracking_instance(manager)
    checkpoint = store.get(instance + ':checkpoint')
    if day < START_DATE or not checkpoint or checkpoint.get('display_date') != day:
        return {'available': False, 'reason': 'Submission tracking has no capture for today.'}
    grouped = defaultdict(lambda: {'submitted_total': 0., 'submitted_count': 0})
    for event in store.records('submission-observation', instance, start=day, end=day):
        user = manager._get_reporting_name(event['user_id'], event.get('username'))
        if not reporting_user(user) or (selected is not None and user not in selected):
            continue
        grouped[user]['submitted_total'] += event['duration_seconds']
        grouped[user]['submitted_count'] += 1
    users = [{'User': user, **values} for user, values in sorted(grouped.items())]
    return {'available': True, 'date': day, 'unit': 'submitted_video_seconds',
            'source': 'observed_task_submission_transition', 'classification_available': False,
            'scope': 'observed_submission_transitions', 'partial': True,
            'values': {'submitted_total': sum(row['submitted_total'] for row in users)},
            'users': users, 'capture': checkpoint['captured_at'],
            'coverage_since': checkpoint['coverage_since'],
            'reconciliation_pending': True}

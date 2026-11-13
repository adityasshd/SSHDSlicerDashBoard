"""Permitted dated status metrics, kept separate from submission-event reports."""
from copy import deepcopy
from datetime import date, datetime, timezone
import math

from slicing_dashboard.management.periods import today_iso
from slicing_dashboard.reporting.dashboard_reports import date_range
from slicing_dashboard.reporting.dashboard_trend import bounded_read
from slicing_dashboard.runtime import viewer_mode

STATUS_METRICS = (
    ('completed', 'Completed video', '#34d399'),
    ('submitted', 'Pending-review video', '#60a5fa'),
    ('rework', 'Rework video', '#fb923c'),
)
STATUS_FIELDS = tuple(field for metric, _, _ in STATUS_METRICS
                      for field in (metric + '_count', metric + '_duration_seconds')) + ('work_duration_seconds',)


def _dates(report_date):
    report_date = report_date or today_iso()
    if date.fromisoformat(report_date).isoformat() != report_date or report_date > today_iso():
        raise ValueError('Choose a report date on or before today.')
    return date_range(report_date)


def status_payload(report_date, records):
    dates = _dates(report_date)
    records = {row['date']: row for row in records if dates[0] <= row.get('date', '') <= dates[-1]}
    history = [records.get(day, {'date': day, 'rows': [], 'metadata': {'available': False}}) for day in dates]
    return {'report_date': dates[-1], 'range_start': dates[0], 'range_end': dates[-1],
            'history': history, 'timezone': 'Asia/Shanghai',
            'users': sorted({row['User'] for day in history for row in day.get('rows', [])}, key=str.casefold),
            'refresh_pending': not viewer_mode()}


def get_status_report_data(manager, report_date=None, force_refresh=False):
    """Read saved full metrics; never start a task scan or an upstream request."""
    dates = _dates(report_date)
    try:
        rows = bounded_read(lambda: manager.get_efficiency_history(
            dates[0], dates[-1], capture_live=False, full_metrics=True))
        payload = status_payload(dates[-1], rows)
    except Exception:
        payload = {**status_payload(dates[-1], []), 'read_error': True}
    return {**payload, 'force_refresh': force_refresh}


def refresh_status_report(manager, saved):
    """Refresh only the selected source day and previous day after saved paint.

    The external efficiency collector renews the longer history. Two dated reads
    keep interactive refresh bounded and retain each day's existing evidence on
    errors. Viewers never collect from the upstream API.
    """
    result = deepcopy(saved)
    result['refresh_pending'] = False
    if viewer_mode():
        return result
    dates = _dates(saved['report_date'])
    try:
        rows = manager.get_efficiency_history(dates[-2], dates[-1],
            force_refresh=saved.get('force_refresh', False), full_metrics=True)
        fresh = {row['date']: row for row in rows}
    except Exception:
        fresh = {}
    history = []
    for day in saved['history']:
        if day['date'] not in dates[-2:]:
            history.append(day)
            continue
        checked = fresh.get(day['date'])
        if checked and checked.get('metadata', {}).get('available'):
            history.append(checked)
        else:
            history.append({**day, 'metadata': {**day.get('metadata', {}), 'error': 'StatusRefreshFailed'}})
    result.update(status_payload(saved['report_date'], history), refresh_pending=False)
    return result


def summarize_status(day, user=None):
    """Missing people/dates/fields are unknown; a recorded zero remains zero."""
    metadata = day.get('metadata', {})
    rows = [row for row in day.get('rows', []) if user is None or row.get('User') == user]
    available = bool(metadata.get('available') and (user is None or rows))
    summary = {'date': day['date'], 'available': available, 'metadata': metadata}
    for field in STATUS_FIELDS:
        values = [row.get(field) for row in rows]
        valid = available and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                  and math.isfinite(v) and v >= 0 for v in values)
        summary[field] = sum(values) if valid else None
    return summary


def capture_stale(metadata):
    if metadata.get('error'):
        return True
    try:
        captured = datetime.fromisoformat(metadata['captured_at'].replace('Z', '+00:00'))
        return captured.tzinfo is None or (datetime.now(timezone.utc) - captured).total_seconds() > 600
    except (KeyError, ValueError, TypeError):
        return True

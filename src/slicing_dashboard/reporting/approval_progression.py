"""Recorded batch approvals and the separate, exact-period completion total."""
from math import isfinite

STAGES = ('Leader', 'Auditor', 'Admin')


def prepare_progression(approvals, dates, selected_users=None, completion=None):
    """Never turn a current batch status into a dated reviewer action.

    Reapprovals count a batch once per stage in the selected review period.
    Completion is supplied by the same captured packet as the completed chart;
    whole-batch duration estimates cannot substitute for task completion hours.
    """
    approvals = approvals or {}
    dates = set(dates)
    selected = set(selected_users) if selected_users is not None else None
    unique = {}
    for row in approvals.get('rows', []):
        if (row.get('date') not in dates or row.get('stage') not in STAGES
                or not row.get('batch_id') or row.get('inferred')
                or row.get('is_synthetic')
                or (selected is not None and row.get('member') not in selected)):
            continue
        key = (row['stage'], row['batch_id'])
        # Retain the latest observed estimate without multiplying repeat passes.
        if key not in unique or (row['date'], row.get('event_id') or '') > (
                unique[key]['date'], unique[key].get('event_id') or ''):
            unique[key] = row
    rows = []
    for stage in STAGES:
        evidence = [row for (name, _), row in unique.items() if name == stage]
        known = [_seconds(row.get('seconds')) for row in evidence]
        missing = sum(value is None for value in known)
        rows.append({'label': stage + ' approved', 'seconds': sum(value for value in known if value is not None),
                     'count': len(evidence), 'unit': 'batches', 'missing': missing,
                     'available': bool(evidence) or bool(approvals.get('complete')),
                     'batch_ids': sorted(row['batch_id'] for row in evidence)})
    available = bool(completion and completion.get('available'))
    values = [row for row in (completion or {}).get('rows', [])
              if selected is None or row.get('User') in selected]
    seconds = [_seconds(row.get('seconds')) for row in values]
    counts = [_seconds(row.get('tasks')) for row in values]
    available = available and all(value is not None for value in seconds)
    rows.append({'label': 'Final completed video', 'seconds': sum(value for value in seconds if value is not None),
                 'count': sum(counts) if all(value is not None for value in counts) else None,
                 'unit': 'tasks', 'missing': 0, 'available': available})
    return {'rows': rows, 'history_complete': bool(approvals.get('complete')),
            'error': approvals.get('error'), 'completion_snapshot': bool((completion or {}).get('is_snapshot'))}


def _seconds(value):
    try:
        number = float(value)
        return number if isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None

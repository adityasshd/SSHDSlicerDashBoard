"""Read a complete current task queue without settlement/date filters."""
from slicing_dashboard.processing.daily_work_source import DailyWorkSource
from slicing_dashboard.processing.daily_work import instant
from datetime import date as calendar_date, datetime


def latest_task_update(task):
    """Return the most recent timestamp from the live task, NOT collector sync.

    An update is a general record modification, not evidence of when a task
    was assigned or returned. We only use it to color undated queue segments
    with an explicitly labelled last-update basis.
    """
    fields = ('updated_on', 'updated_at', 'status_updated_at',
              'modified_at', 'last_modified_at')
    candidates = []
    for field in fields:
        raw = task.get(field)
        if not raw:
            continue
        try:
            # Date-only values should not shift one day back on UTC+8 -> IST.
            text = str(raw)
            if len(text) == 10:
                date_value = calendar_date.fromisoformat(text)
                stamp = instant(date_value.isoformat() + 'T12:00:00+08:00')
            else:
                stamp = instant(raw)
        except (ValueError, TypeError, OverflowError):
            continue
        if stamp is not None:
            candidates.append((stamp, field))
    latest = task.get('_latest_update')
    if latest:
        try:
            stamp = instant(latest)
            if stamp is not None:
                candidates.append((stamp, task.get('_latest_update_basis') or 'updated_on'))
        except (ValueError, TypeError, OverflowError):
            pass
    return max(candidates, key=lambda value: value[0]) if candidates else (None, None)


def assignment_metadata(task, batches, returns=()):
    """Attach dates to live quantities; ledger rows never create assignments.

    Prefer an exact batch link or original timestamp. Legacy return history
    can link rework tasks. An account ledger date is usable when its active
    batches share one date; ambiguous dates remain unknown.
    """
    def date(value):
        try:
            if value and len(str(value)) == 10:
                return calendar_date.fromisoformat(str(value)).isoformat()
            stamp = instant(value)
            return stamp.date().isoformat() if stamp else ''
        except (ValueError, TypeError, OverflowError):
            return ''

    direct_date = date(task.get('assigned_at') or task.get('assignment_date'))
    def same_account(row):
        if task.get('slicer_id') is not None and row.get('user_id') is not None:
            return str(row['user_id']) == str(task['slicer_id'])
        return bool(task.get('slicer') and row.get('username') == task['slicer'])

    batch_id = task.get('assignment_batch_id') or task.get('batch_id')
    legacy = task.get('slice_batch')
    if not batch_id and legacy is not None:
        linked = {row.get('batch_id') for row in returns
                  if same_account(row)
                  and str(row.get('legacy_batch_number')) == str(legacy) and row.get('batch_id')}
        if len(linked) == 1:
            batch_id = linked.pop()
    candidates = [row for row in batches if row.get('batch_id') == batch_id] if batch_id else []
    if not candidates and not batch_id:
        candidates = [row for row in batches
                      if row.get('status') in ('batch_member_assigned', 'batch_rework')
                      and ((task.get('slicer') and row.get('username') == task.get('slicer'))
                           or (task.get('slicer_id') is not None
                               and str(row.get('assignee_id')) == str(task['slicer_id'])))]
        # A legacy identifier retained by a newer ledger is an exact link.
        exact = [row for row in candidates if legacy is not None
                 and str(row.get('legacy_batch_number')) == str(legacy)]
        if exact:
            candidates = exact
            batch_id = exact[0].get('batch_id') if len(exact) == 1 else None
    dates = {date(row.get('assigned_at') or row.get('batch_date')) for row in candidates}
    known = direct_date or (next(iter(dates)) if len(dates) == 1 and '' not in dates else '')
    # Match the exact batch (or account + legacy number), never another batch
    # belonging to the same person. Repeated returns use the latest timestamp.
    matching = [row for row in returns
                if (batch_id and row.get('batch_id') == batch_id)
                or (not batch_id and legacy is not None and same_account(row)
                    and str(row.get('legacy_batch_number')) == str(legacy))]
    if not batch_id and len({row['batch_id'] for row in matching if row.get('batch_id')}) > 1:
        matching = []
    returned = max([date(task.get('slice_returned_at') or task.get('returned_at'))]
                   + [date(row.get('returned_at')) for row in matching])
    update_stamp, update_field = latest_task_update(task)
    # Future task updates are clock/data errors; never color them as Today.
    from slicing_dashboard.management.periods import today_iso
    update_date = (update_stamp.date().isoformat()
                   if update_stamp and update_stamp.date() <= calendar_date.fromisoformat(today_iso())
                   else '')
    return {'AssignedDate': known, 'ReturnedDate': returned,
            'UpdatedDate': update_date,
            'UpdateDateBasis': update_field if update_date else 'Unknown',
            'BatchID': batch_id or ', '.join(sorted(
                str(row['batch_id']) for row in candidates if row.get('batch_id') and known)),
            'AssignmentDateBasis': ('Assignment timestamp' if direct_date else
                                    'Batch assignment date' if known and batch_id else
                                    'Account batch date' if known else 'Unknown')}


def fetch_queue(scraper, status):
    source = DailyWorkSource(scraper)
    tasks, seen_ids, seen_cursors = [], set(), set()
    page, cursor = 1, None
    while True:
        params = {'status': status, 'workflow_type': 'slice', 'page_size': 200, 'page': page}
        if cursor:
            params['cursor'] = cursor
        payload = source.request('/api/slice/tasks', params=params)
        if not isinstance(payload.get('data'), list):
            raise ValueError('Current assignment inventory response is invalid')
        rows, meta = payload.get('data', []), payload.get('meta', {})
        if meta.get('total_capped'):
            raise ValueError('Current assignment inventory is capped')
        new = 0
        for row in rows:
            if row.get('status') != status:
                continue
            identifier = row.get('id')
            if not identifier:
                raise ValueError('Current assignment inventory has no task identifier')
            if identifier not in seen_ids:
                seen_ids.add(identifier)
                tasks.append(row)
                new += 1
        has_more = meta.get('has_more')
        if has_more is None:
            has_more = page * int(meta.get('page_size') or 200) < int(meta.get('total') or 0)
        if not has_more:
            return tasks
        if not rows or not new:
            raise ValueError('Current assignment inventory pagination did not advance')
        cursor = meta.get('next_cursor')
        if cursor and cursor in seen_cursors:
            raise ValueError('Current assignment inventory repeated a cursor')
        if cursor:
            seen_cursors.add(cursor)
        page += 1

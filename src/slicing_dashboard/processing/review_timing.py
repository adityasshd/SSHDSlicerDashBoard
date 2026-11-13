"""Recover missing queue durations from the same tasks' current time ranges."""
from math import isfinite

from slicing_dashboard.processing.daily_work_source import DailyWorkSource
from slicing_dashboard.runtime import ReadExecutor


def nonnegative(value):
    if value is None or isinstance(value, bool):
        raise ValueError('Missing review task timing')
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError('Invalid review task timing')
    return value


def overview_tasks(source, actor_id, identifiers):
    """Read every filtered page using the authenticated actor, never a member ID."""
    tasks, cursors, total = {}, set(), None
    body = {'user_id': actor_id, 'task_ids': sorted(identifiers),
            'status_group': 'all', 'page_size': 200, 'page': 1}
    for _ in range(100):
        payload = source.request('/api/tasks/assigned/overview', body=body)
        if not isinstance(payload, dict):
            raise ValueError('Invalid review timing overview')
        rows, meta = payload.get('items'), payload.get('meta', {})
        expected = payload.get('total')
        if (not isinstance(rows, list) or not isinstance(meta, dict)
                or type(expected) is not int or not 0 <= expected <= len(identifiers)
                or meta.get('total_capped') or type(meta.get('has_more')) is not bool):
            raise ValueError('Incomplete review timing overview')
        if total is not None and expected != total:
            raise ValueError('Review timing overview changed during pagination')
        total = expected
        for row in rows:
            if not isinstance(row, dict) or row.get('id') not in identifiers:
                raise ValueError('Review timing overview returned an unexpected task')
            if row['id'] in tasks:
                raise ValueError('Review timing overview repeated a task')
            tasks[row['id']] = row
        if not meta['has_more']:
            if len(tasks) != total:
                raise ValueError('Review timing overview ended early')
            return tasks
        cursor = meta.get('next_cursor')
        if not rows or not cursor or cursor in cursors:
            raise ValueError('Review timing pagination did not advance')
        cursors.add(cursor)
        body = {**body, 'cursor': cursor, 'page': body['page'] + 1}
    raise ValueError('Review timing pagination limit reached')


def recover_review_durations(scraper, tasks):
    """Keep queue membership/owners/stages; recover only missing or zero seconds.

    A changing task, incomplete overview, or unavailable range fails the capture
    rather than silently presenting unobserved work as zero hours.
    """
    result, missing = [], {}
    for original in tasks:
        row = dict(original)
        value = row.get('duration_seconds')
        seconds = None if value is None else nonnegative(value)
        row.update(queue_duration_seconds=value, duration_source='/api/slice/tasks')
        if seconds is None or seconds == 0:
            missing[row['id']] = row
        else:
            row['duration_seconds'] = seconds
        result.append(row)
    if not missing:
        return result

    source = DailyWorkSource(scraper)
    actor = source.request('/api/auth/me').get('id')
    if type(actor) is not int or actor < 1:
        raise ValueError('Authenticated review actor is unavailable')
    timings = overview_tasks(source, actor, set(missing))
    # Some role-specific overviews omit a stage. Read those exact tasks using
    # the same authenticated session; never impersonate their assignees.
    absent = sorted(set(missing) - timings.keys())
    with ReadExecutor(max_workers=2) as pool:
        details = pool.map(lambda identifier: source.request('/api/tasks/' + identifier), absent)
        for identifier, detail in zip(absent, details):
            timings[identifier] = detail
    for identifier, row in missing.items():
        timing = timings[identifier]
        if (not isinstance(timing, dict) or timing.get('id') != identifier
                or timing.get('status') != row.get('status')
                or row.get('slicer_id') is None or timing.get('slicer_id') is None
                or str(timing['slicer_id']) != str(row['slicer_id'])):
            raise ValueError('Review task stage or owner changed; retry capture')
        start, end = nonnegative(timing.get('start')), nonnegative(timing.get('end'))
        if end <= start:
            raise ValueError('Review task has no recoverable time range')
        row.update(duration_seconds=end - start, duration_start=start, duration_end=end,
                   duration_source=('/api/tasks/{task_id}' if identifier in absent
                                    else '/api/tasks/assigned/overview'))
    return result

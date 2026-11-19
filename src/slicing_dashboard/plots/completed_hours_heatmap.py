"""Period-completed task hours have no defensible November return-tier allocation.

Use independently captured efficiency data. Batch-cohort/video durations are
never substituted for an unavailable period-completion capture.
"""
from math import isfinite
from html import escape

from slicing_dashboard.plots.guardrails import safe_chart, state_figure
from slicing_dashboard.plots.intensity_chart import intensity_chart
from slicing_dashboard.plots.theme import format_seconds


def completion_total(completion, selected=None):
    """Return verified seconds or None for unavailable/invalid period evidence."""
    if not isinstance(completion, dict) or not completion.get('available'):
        return None
    seen, total = set(), 0.
    for row in completion.get('rows', ()):
        if not isinstance(row, dict):
            return None
        user = row.get('User')
        if not isinstance(user, str) or not user or user in seen:
            return None
        seen.add(user)
        try:
            value = float(row['seconds'])
        except (TypeError, ValueError, KeyError):
            return None
        if not isfinite(value) or value < 0:
            return None
        if selected is None or user in selected:
            total += value
    return total if isfinite(total) else None


@safe_chart
def build_completed_hours_heatmap(completion, is_dark=True, selected=None, compact=False):
    """One-source-date completion column, never inferred return tiers."""
    if not isinstance(completion, dict) or not completion.get('available'):
        return state_figure('Verified completed hours unavailable for this date range.', is_dark)
    if selected == []:
        return state_figure('No users selected.', is_dark)
    data = completion.get('rows')
    if not isinstance(data, list):
        return state_figure('Verified completed hours unavailable.', is_dark)
    seen, rows = set(), []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get('User'), str):
            raise ValueError('Invalid completed-hour user')
        user = item['User']
        if not user or user in seen:
            raise ValueError('Duplicate or empty completed-hour user')
        seen.add(user)
        if selected is not None and user not in selected:
            continue
        seconds = float(item['seconds'])
        if not isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid completed-hour duration')
        tasks = item.get('tasks')
        if tasks is not None:
            if isinstance(tasks, bool) or not isinstance(tasks, (int, float)) or int(tasks) != tasks or tasks < 0:
                raise ValueError('Invalid completed-task count')
            tasks = int(tasks)
        rows.append((user, seconds, tasks))
    if not rows:
        return state_figure('No completed-hour rows for selected users.', is_dark)
    rows.sort(key=lambda item: (-item[1], item[0].casefold()))
    seconds_total = sum(item[1] for item in rows)
    tasks_total = sum(item[2] for item in rows) if all(item[2] is not None for item in rows) else None
    users = [item[0] for item in rows] + ['<b>Total</b>']
    values = [[item[1] / 3600] for item in rows] + [[seconds_total / 3600]]
    counts = [[item[2]] for item in rows] + [[tasks_total]]
    labels = [[format_seconds(item[1], compact=True)] for item in rows] + [[format_seconds(seconds_total, compact=True)]]
    custom = [
        [[escape(item[0]), format_seconds(item[1]), item[2] if item[2] is not None else 'Unavailable']]
        for item in rows
    ] + [[['Total', format_seconds(seconds_total), tasks_total if tasks_total is not None else 'Unavailable']]]
    caption = (
        'Exact source-date completed video hours · not original batch duration'
        '<br>Return tier attribution unavailable without task-to-batch evidence'
    )
    figure = intensity_chart(
        users, ['Completed<br>hours'],
        {'Hours': (values, labels),
         'Tasks': (counts, [[str(row[0]) if row[0] is not None else '—'] for row in counts])},
        custom,
        '<b>%{customdata[0]}</b><br>Completed: %{customdata[1]}'
        '<br>Tasks: %{customdata[2]}<extra></extra>',
        'Completed video hours' if compact else 'Completed video · verified source hours',
        is_dark, '' if compact else caption, show_counts=False,
    )
    figure.update_layout(meta={**figure.layout.meta,
        'metric': 'source_date_completed_seconds',
        'completed_seconds': seconds_total,
        'unattributed_tier_hours': True,
        'range_start': completion.get('start'),
        'range_end': completion.get('end')})
    return figure

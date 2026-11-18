"""Verified period completion, kept separate from pending batch inventory.

The batch ledger has no completion date. It cannot allocate period-completed
task hours among return tiers. Never prorate those hours by batch counts.
"""
from html import escape

from slicing_dashboard.plots.guardrails import safe_chart, state_figure
from slicing_dashboard.plots.intensity_chart import intensity_chart
from slicing_dashboard.plots.theme import format_seconds
from slicing_dashboard.reporting.rework_tiers import TIERS, prepare_rework_stacks


@safe_chart
def build_period_rework(frame, completion, state, is_dark, selected=None, pending_available=True):
    completed = {row['User']: row for row in completion.get('rows', [])
                 if selected is None or row['User'] in selected}
    available = completion.get('available', False)
    pending = frame[frame['Completion State'] == 'Pending approvals'] if 'Completion State' in frame else frame.iloc[:0]
    if selected is not None and 'User' in pending:
        pending = pending[pending.User.isin(selected)]
    stacks = prepare_rework_stacks(pending) if not pending.empty else {}
    if state == 'Completed':
        if not available:
            return state_figure('Period completion unavailable; lifetime batch totals are not substituted.', is_dark)
        users = sorted(completed, key=lambda name: (-completed[name]['seconds'], name))
        categories = ['No<br>Rework', '1<br>Rework', '2<br>Reworks', '3+<br>Reworks', 'Unknown', 'Period<br>completed']
    else:
        users = sorted(set(completed) | {name for name, _ in stacks})
        categories = ['No<br>Rework', '1<br>Rework', '2<br>Reworks', '3+<br>Reworks', 'Unknown', 'Period<br>completed']
    if not users:
        return state_figure('No work for this selection.', is_dark)
    hours, counts, labels, custom = [], [], [], []
    for user in users:
        row = completed.get(user, {})
        duration = float(row.get('seconds', 0)) / 3600 if available else None
        if state == 'Completed':
            row_hours, row_counts = [None] * 5, [None] * 5
        else:
            stack = stacks.get((user, 'Pending approvals'))
            row_hours = list(stack['hours']) if stack else [0 if pending_available else None] * 5
            row_counts = list(stack['counts']) if stack else [0 if pending_available else None] * 4
        row_hours.append(duration)
        row_counts.append(row.get('tasks', 0) if available else None)
        units = ['batches'] * 5 + ['tasks']
        hours.append(row_hours)
        counts.append(row_counts)
        labels.append([format_seconds(value * 3600, compact=True) if value is not None else '—' for value in row_hours])
        custom.append([[escape(user), category, format_seconds(value * 3600) if value is not None else 'Unavailable',
                        count if count is not None else 'Unavailable', unit]
                       for category, value, count, unit in zip(categories, row_hours, row_counts, units)])
    total_hours = [sum(column) if all(value is not None for value in column) else None for column in zip(*hours)]
    total_counts = [sum(column) if all(value is not None for value in column) else None for column in zip(*counts)]
    users.append('<b>Total</b>')
    hours.append(total_hours)
    counts.append(total_counts)
    labels.append([format_seconds(value * 3600, compact=True) if value is not None else '—' for value in total_hours])
    custom.append([['Total', category, format_seconds(value * 3600) if value is not None else 'Unavailable',
                    count if count is not None else 'Unavailable', 'tasks' if index == 5 else 'batches']
                   for index, (category, value, count) in enumerate(zip(categories, total_hours, total_counts))])
    return intensity_chart(users, categories,
        {'Hours': (hours, labels), 'Counts': (counts, [[str(value) for value in row] for row in counts])}, custom,
        '<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]}<br>%{customdata[3]} %{customdata[4]}<extra></extra>',
        'Completed video in selected period' if state == 'Completed' else 'Period completion and pending batches',
        is_dark,
        'Period completed total matches Overview<br>Return-tier hours unavailable<br>No dated batch completion evidence'
        if state == 'Completed' else
        'Return tiers: pending batch inventory<br>Completed: period task output<br>Different scopes; columns are not additive')

"""Current pending review intensity by user and stage."""
from html import escape

from slicing_dashboard.plots.guardrails import safe_chart, checked_frame, state_figure
from slicing_dashboard.plots.intensity_chart import intensity_chart
from slicing_dashboard.plots.theme import format_seconds

STAGES = ['Pending Leader', 'Pending Auditor', 'Pending Admin']


@safe_chart
def build_pending_chart(pending_df, is_dark: bool, show_counts=False):
    """Show duration with optional task counts from the same queue capture."""
    if pending_df is not None and pending_df.attrs.get('pending_error'):
        return state_figure('Pending review unavailable. Refresh to retry.', is_dark)
    frame = checked_frame(pending_df, ['User', 'Stage', 'Duration', 'Count'], ['Duration', 'Count'])
    if frame.empty:
        return state_figure('No pending reviews queued.', is_dark)
    if not frame.Stage.isin(STAGES).all() or (frame.Count % 1 != 0).any():
        raise ValueError('Invalid pending review stages or task counts')
    frame = frame[(frame.Duration > 0) | (frame.Count > 0)]
    if frame.empty:
        return state_figure('No pending reviews queued.', is_dark)
    users = list(frame.groupby('User').Duration.sum().sort_values(ascending=False, kind='stable').index)
    cells = {}
    for (user, stage), rows in frame.groupby(['User', 'Stage']):
        ids = sorted({item.strip() for raw in rows.get('IDs', []) for item in str(raw or '').split(',') if item.strip()})
        cells[user, stage] = (rows.Duration.sum(), int(rows.Count.sum()), ', '.join(ids) or 'Unavailable')
    total_label = '<b>Total</b>'
    for stage in STAGES:
        stage_cells = [cell for (user, cell_stage), cell in cells.items() if cell_stage == stage]
        ids = sorted({account.strip() for cell in stage_cells for account in cell[2].split(',')
                      if account.strip() and account.strip() != 'Unavailable'})
        cells[total_label, stage] = (sum(cell[0] for cell in stage_cells),
                                    sum(cell[1] for cell in stage_cells), ', '.join(ids) or 'None')
    users.append(total_label)
    hours, counts, labels, custom = [], [], [], []
    for user in users:
        row_hours, row_counts, row_labels, row_custom = [], [], [], []
        for stage in STAGES:
            seconds, count, ids = cells.get((user, stage), (0, 0, 'None'))
            row_hours.append(seconds / 3600)
            row_counts.append(count)
            row_labels.append(format_seconds(seconds, compact=True))
            row_custom.append([escape('Total' if user == total_label else user), stage, format_seconds(seconds), count, escape(ids)])
        hours.append(row_hours)
        counts.append(row_counts)
        labels.append(row_labels)
        custom.append(row_custom)
    figure = intensity_chart(
        users, ['Leader', 'Auditor', 'Admin'],
        {'Hours': (hours, labels), 'Tasks': (counts, [[str(value) for value in row] for row in counts])},
        custom, '<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]}<br>'
                '%{customdata[3]} tasks<br>IDs: %{customdata[4]}<extra></extra>',
        'Pending review intensity', is_dark, 'Current queue · user by review stage',
        show_counts=show_counts,
    )
    figure.update_layout(meta={**figure.layout.meta, 'captured_at': pending_df.attrs.get('captured_at')})
    return figure

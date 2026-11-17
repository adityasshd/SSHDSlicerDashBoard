"""Compact summaries of the existing queue and common batch approval cohort."""
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart, checked_frame, state_figure
from slicing_dashboard.plots.theme import theme_ctx, format_seconds

REVIEW_COLORS = ['#c2fd75', '#165a50', '#a78bfa']
REVIEW_STAGES = ['Pending Leader', 'Pending Auditor', 'Pending Admin']


@safe_chart(height=340)
def build_review_workload_donut(frame, is_dark=True):
    """A part-to-whole view of mutually exclusive current review stages."""
    frame = checked_frame(frame, ['Stage', 'Duration', 'Count'], ['Duration', 'Count'])
    if frame.empty:
        return state_figure('No pending reviews queued.', is_dark, 340)
    if not frame['Stage'].isin(REVIEW_STAGES).all():
        raise ValueError('Unknown review stage')
    grouped = frame.groupby('Stage')[['Duration', 'Count']].sum()
    seconds = [float(grouped.loc[stage, 'Duration']) if stage in grouped.index else 0 for stage in REVIEW_STAGES]
    counts = [int(grouped.loc[stage, 'Count']) if stage in grouped.index else 0 for stage in REVIEW_STAGES]
    total = sum(seconds)
    if total == 0:
        return state_figure('No pending video duration.' if sum(counts) else 'No pending reviews queued.', is_dark, 340)
    theme = theme_ctx(is_dark)
    figure = go.Figure(go.Pie(
        labels=['Leader', 'Auditor', 'Admin'], values=seconds, hole=.76, sort=False,
        direction='clockwise', rotation=90, textinfo='none',
        marker={'colors': REVIEW_COLORS if is_dark else ['#165a50', '#78b844', '#8b5cf6'], 'line': {'width': 3, 'color': '#030e09' if is_dark else '#ffffff'}},
        customdata=[[format_seconds(value), count] for value, count in zip(seconds, counts)],
        hovertemplate='<b>%{label} review</b><br>%{customdata[0]}<br>%{customdata[1]} tasks<extra></extra>',
    ))
    figure.add_annotation(text=f'<b>{format_seconds(total, compact=True)}</b><br>video hours',
                          x=.5, y=.5, xref='paper', yref='paper', showarrow=False,
                          font={'size': 17})
    figure.update_layout(template=theme['template'], height=340, showlegend=True,
        title={'text': 'Review workload mix', 'subtitle': {'text': 'Current task queue · independent of period dates', 'font': {'size': 10}}}, paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'color': theme['font_color'], 'family': 'Inter, sans-serif'},
        hoverlabel={'bgcolor': theme['hover_bg'], 'font_color': theme['hover_fg']},
        margin={'l': 20, 'r': 20, 't': 54, 'b': 90},
        legend={'orientation': 'h', 'x': .5, 'xanchor': 'center', 'y': -.12,
                'yanchor': 'top', 'entrywidth': 70, 'font': {'size': 11},
                'itemclick': False, 'itemdoubleclick': False},
        xaxis={'visible': False}, yaxis={'visible': False}, uirevision='review-workload')
    return figure


@safe_chart(height=340)
def build_approval_progression(payload, dates, selected_users=None, is_dark=True, completion=None):
    """Dated review decisions plus the exact selected-period completion source.

    A current batch status and its inventory date cannot establish when it
    completed. Never substitute that lifetime batch duration for period output.
    """
    from slicing_dashboard.reporting.approval_progression import prepare_progression
    if selected_users == []:
        return state_figure('No users selected.', is_dark, 340)
    report = prepare_progression(payload, dates, selected_users, completion)
    rows = report['rows'][:2]
    final = report['rows'][-1]
    if final['available']:
        rows.append({**final, 'label': 'Admin / completed', 'batch_count': None})
    else:
        # A retained Admin review is an estimate from dated evidence, never the
        # current batch-completed inventory or an undated synthetic prerequisite.
        rows.append({**report['rows'][2], 'label': 'Admin approved'})
    if not any(row['available'] for row in rows):
        return state_figure('No dated approval or period completion data for this selection.', is_dark, 340)
    values, texts, custom = [], [], []
    for row in rows:
        available = row['available'] and not row['missing']
        duration = format_seconds(row['seconds']) if available else 'Unavailable'
        count = row.get('batch_count', row['count'])
        count_label = f'{int(count)} {"batch" if count == 1 else "batches"}' if count is not None else 'Batch count unavailable'
        values.append(row['seconds'] / 3600 if available else None)
        texts.append(duration + '<br>' + count_label)
        custom.append([duration, count_label,
                       f"{int(row['count'])} completed tasks" if row['unit'] == 'tasks' and row['count'] is not None else
                       'Unique batches approved in this period; whole-batch duration estimate'])
    theme = theme_ctx(is_dark)
    colors = REVIEW_COLORS if is_dark else ['#165a50', '#78b844', '#8b5cf6']
    figure = go.Figure(go.Funnel(
        y=[row['label'] for row in rows], x=values, orientation='h',
        text=texts, texttemplate='%{text}', textposition='inside', customdata=custom,
        marker={'color': colors, 'line': {'width': 0}},
        connector={'line': {'width': 0}},
        hovertemplate='<b>%{y}</b><br>%{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}<extra></extra>',
    ))
    for row in rows:
        if not row['available'] or row['missing']:
            figure.add_annotation(x=.5, xref='paper', y=row['label'], yref='y',
                                  text='Unavailable', showarrow=False, font={'color': theme['font_color']})
    figure.update_layout(template=theme['template'], height=340,
        title={'text': 'Approval progression', 'subtitle': {'text':
               'Approvals within selected period<br>Admin completion matches Overview<br>Stage totals are independent',
               'font': {'size': 10}}},
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'], showlegend=False,
        font={'color': theme['font_color'], 'family': 'Inter, sans-serif'},
        margin={'l': 108, 'r': 20, 't': 82, 'b': 24},
        xaxis={'visible': False}, yaxis={'automargin': True}, uirevision='approval-progression-period')
    return figure

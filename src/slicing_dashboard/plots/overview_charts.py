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
    """Three nested approval stages for the same dated *batch cohort*.

    Values are unique batches by latest known outcome, not task completions
    and not independently summed review-event durations. The separate
    completed-hours chart remains the authoritative period task metric.
    The optional completion argument is retained for existing callers only.
    """
    from slicing_dashboard.reporting.approval_funnel import prepare_funnel, STAGES
    if selected_users == []:
        return state_figure('No users selected.', is_dark, 340)
    if not isinstance(payload, dict) or not payload.get('rows'):
        return state_figure('No saved batch approval cohort for this period.', is_dark, 340)
    scope = set(dates)
    selected = set(selected_users) if selected_users is not None else None
    rows = [row for row in payload['rows'] if row.get('date') in scope and
            (selected is None or row.get('member') in selected)]
    if not rows or all(all(outcome == 'Unknown' for outcome in row.get('outcomes', [])) for row in rows):
        return state_figure('No recorded batch approval stages for this selection.', is_dark, 340)
    _, totals = prepare_funnel(payload, dates, selected_users)
    values = [totals[stage]['Approved']['count'] for stage in STAGES]
    if not any(values):
        return state_figure('No batches have passed a review stage yet.', is_dark, 340)
    if any(left < right for left, right in zip(values, values[1:])):
        raise ValueError('Approval stages do not form a nested batch cohort')
    descriptions = []
    for stage, count in zip(STAGES, values):
        metrics = totals[stage]['Approved']
        hours = (format_seconds(metrics['seconds'])
                 if not metrics['missing'] else 'Incomplete duration evidence')
        descriptions.append([f'{count} verified batch outcomes', hours])
    theme = theme_ctx(is_dark)
    colors = REVIEW_COLORS if is_dark else ['#165a50', '#78b844', '#8b5cf6']
    figure = go.Figure(go.Funnel(
        y=list(STAGES), x=values, orientation='h',
        texttemplate='%{value} batches', textposition='inside',
        customdata=descriptions,
        marker={'color': colors, 'line': {'width': 0}},
        connector={'line': {'color': 'rgba(148,163,184,.22)', 'width': 1}},
        hovertemplate='<b>%{y} approved</b><br>%{x} batches'
                      '<br>Batch-cohort video duration: %{customdata[1]}<extra></extra>',
    ))
    figure.update_layout(template=theme['template'], height=340,
        title={'text': 'Batch approval progression',
               'subtitle': {'text': 'One batch cohort · latest known outcome'
                           '<br>Not period-completed task hours',
                            'font': {'size': 10}}},
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'], showlegend=False,
        font={'color': theme['font_color'], 'family': 'Inter, sans-serif'},
        hoverlabel={'bgcolor': theme['hover_bg'], 'font_color': theme['hover_fg']},
        margin={'l': 78, 'r': 20, 't': 73, 'b': 24},
        xaxis={'visible': False}, yaxis={'automargin': True}, uirevision='approval-cohort-v2',
        meta={'metric': 'distinct_batch_stage_count', 'stage_counts': values})
    return figure

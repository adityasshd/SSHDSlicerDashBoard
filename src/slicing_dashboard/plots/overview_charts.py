"""Compact summaries of the existing queue and common batch approval cohort."""
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart, checked_frame, state_figure
from slicing_dashboard.plots.theme import theme_ctx, format_seconds
from slicing_dashboard.reporting.approval_funnel import prepare_funnel, STAGES

REVIEW_COLORS = ['#F59E0B', '#8B5CF6', '#06B6D4']
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
        marker={'colors': REVIEW_COLORS, 'line': {'width': 3, 'color': '#030e09' if is_dark else '#ffffff'}},
        customdata=[[format_seconds(value), count] for value, count in zip(seconds, counts)],
        hovertemplate='<b>%{label} review</b><br>%{customdata[0]}<br>%{customdata[1]} tasks<extra></extra>',
    ))
    figure.add_annotation(text=f'<b>{format_seconds(total, compact=True)}</b><br>video hours',
                          x=.5, y=.5, xref='paper', yref='paper', showarrow=False,
                          font={'size': 17})
    figure.update_layout(template=theme['template'], height=340, showlegend=True,
        title='Review workload mix', paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'color': theme['font_color'], 'family': 'Inter, sans-serif'},
        hoverlabel={'bgcolor': theme['hover_bg'], 'font_color': theme['hover_fg']},
        margin={'l': 20, 'r': 20, 't': 54, 'b': 90},
        legend={'orientation': 'h', 'x': .5, 'xanchor': 'center', 'y': -.12,
                'yanchor': 'top', 'entrywidth': 70, 'font': {'size': 11},
                'itemclick': False, 'itemdoubleclick': False},
        xaxis={'visible': False}, yaxis={'visible': False}, uirevision='review-workload')
    return figure


@safe_chart(height=340)
def build_approval_progression(payload, dates, selected_users=None, is_dark=True):
    """Use verified nested pass counts for the same cohort, not live queue sizes."""
    if not payload or not payload.get('rows'):
        return state_figure('No batch approval cohort for this period.', is_dark, 340)
    rows = [row for row in payload['rows'] if row['date'] in dates and
            (not selected_users or row['member'] in selected_users)]
    if not rows or all(all(outcome == 'Unknown' for outcome in row['outcomes']) for row in rows):
        return state_figure('No verified batch approval stages for this selection.', is_dark, 340)
    _, totals = prepare_funnel(payload, dates, selected_users)
    values = [totals[stage]['Approved']['count'] for stage in STAGES]
    if not any(values):
        return state_figure('No batches have passed a review stage yet.', is_dark, 340)
    if not all(left >= right for left, right in zip(values, values[1:])):
        raise ValueError('Approval stages do not form a nested cohort')
    theme = theme_ctx(is_dark)
    figure = go.Figure(go.Funnel(
        y=list(STAGES), x=values, orientation='h', texttemplate='%{value} batches',
        textposition='inside', marker={'color': REVIEW_COLORS, 'line': {'width': 0}},
        connector={'line': {'color': 'rgba(148,163,184,.22)', 'width': 1}},
        hovertemplate='<b>%{y} approved</b><br>%{x} batches<extra></extra>',
    ))
    figure.update_layout(template=theme['template'], height=340, title='Approval progression',
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'], showlegend=False,
        font={'color': theme['font_color'], 'family': 'Inter, sans-serif'},
        hoverlabel={'bgcolor': theme['hover_bg'], 'font_color': theme['hover_fg']},
        margin={'l': 68, 'r': 20, 't': 54, 'b': 24},
        xaxis={'visible': False}, yaxis={'automargin': True}, uirevision='approval-progression')
    return figure

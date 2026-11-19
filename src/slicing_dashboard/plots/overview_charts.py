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
def build_approval_progression(payload, dates, selected_users=None, is_dark=True,
                               completion=None, unit='Batches'):
    """Compare only like-for-like quantities.

    Hours: only the exact-range source-date Completed video duration is known.
    The selected dates lack auditable per-stage approval timestamps for
    Leader/Auditor. They are shown as unavailable, never inferred from a batch's
    original duration. Admin completion is explicitly labelled as source status,
    not a claim about the Admin action timestamp.

    Batches: nested *current* batch-stage counts for one batch-date cohort.
    No original batch durations are exposed as approval hours.
    """
    from slicing_dashboard.plots.completed_hours_heatmap import completion_total
    from slicing_dashboard.reporting.approval_funnel import prepare_funnel, STAGES
    if unit not in ('Hours', 'Batches'):
        raise ValueError('Unknown approval progression unit')
    if selected_users == []:
        return state_figure('No users selected.', is_dark, 340)
    theme = theme_ctx(is_dark)
    colors = REVIEW_COLORS if is_dark else ['#165a50', '#78b844', '#8b5cf6']
    if unit == 'Hours':
        seconds = completion_total(completion, selected_users)
        if seconds is None:
            return state_figure('Verified completed hours unavailable for this period. '
                                'Batch video duration is not substituted.', is_dark, 340)
        figure = go.Figure(go.Bar(
            y=['Admin completed'], x=[seconds / 3600], orientation='h',
            marker={'color': colors[2]}, width=.45,
            text=[format_seconds(seconds, compact=True)], textposition='outside',
            customdata=[format_seconds(seconds)],
            hovertemplate='<b>Completed video · Admin status</b><br>'
                          '%{customdata}<br>Exact source-date range'
                          '<br>Not a dated Admin approval event<extra></extra>',
        ))
        for stage, y in [('Leader approval', .80), ('Auditor approval', .54)]:
            figure.add_annotation(text=f'{stage} hours: unavailable', x=.02, y=y,
                xref='paper', yref='paper', xanchor='left', showarrow=False,
                font={'size': 11, 'color': theme['font_color']})
        snapshot_note = (f"<br>Saved through {completion.get('end', 'unknown date')}; not live"
                         if completion.get('is_snapshot') else '')
        figure.update_layout(
            template=theme['template'], height=340,
            title={'text': 'Approval progression · verified hours',
                   'subtitle': {'text': 'Completed video: ' + format_seconds(seconds) +
                                '<br>Leader/Auditor dated approval hours unavailable' +
                                snapshot_note, 'font': {'size': 10}}},
            paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
            font={'color': theme['font_color'], 'family': 'Inter, sans-serif'},
            hoverlabel={'bgcolor': theme['hover_bg'], 'font_color': theme['hover_fg']},
            margin={'l': 80, 'r': 110, 't': 80, 'b': 25},
            showlegend=False,
            xaxis={'title': 'Completed video hours', 'range': [0, max(seconds / 3600 * 1.25, 1)]},
            yaxis={'categoryorder': 'array', 'categoryarray': ['Admin completed']},
            uirevision='verified-completed-hours',
            meta={'metric': 'source_date_completed_seconds', 'verified_seconds': seconds,
                  'leader_hours': None, 'auditor_hours': None,
                  'admin_completed_status_hours': seconds, 'unit': 'Hours',
                  'saved_capture': bool(completion.get('is_snapshot'))},
        )
        return figure
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
    figure = go.Figure(go.Funnel(
        y=list(STAGES), x=values, orientation='h',
        texttemplate='%{value} batches', textposition='inside',
        marker={'color': colors, 'line': {'width': 0}},
        connector={'line': {'color': 'rgba(148,163,184,.22)', 'width': 1}},
        hovertemplate='<b>%{y} · latest status</b><br>%{x} batches'
                      '<br>Not dated approval hours<extra></extra>',
    ))
    figure.update_layout(template=theme['template'], height=340,
        title={'text': 'Batch stage progression · counts',
               'subtitle': {'text': 'Current batch-status cohort · not dated approvals'
                            '<br>Use Hours for exact-range completed video',
                            'font': {'size': 10}}},
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'], showlegend=False,
        font={'color': theme['font_color'], 'family': 'Inter, sans-serif'},
        hoverlabel={'bgcolor': theme['hover_bg'], 'font_color': theme['hover_fg']},
        margin={'l': 78, 'r': 20, 't': 73, 'b': 24},
        xaxis={'visible': False}, yaxis={'automargin': True}, uirevision='approval-cohort-v3',
        meta={'metric': 'distinct_batch_stage_count', 'stage_counts': values,
              'unit': 'Batches'})
    return figure

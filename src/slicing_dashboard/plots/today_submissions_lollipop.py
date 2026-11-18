"""Today's submitted VIDEO DURATION: line for all submitted, lollipops for rework.

The Daily submission report supplies dated per-user video seconds. Submitted
includes fresh, old rework and same-day rework; those subsets must not be added
again to the plotted total. Never substitute screen time or batch-return counts.
"""
from math import isfinite

import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart, state_figure
from slicing_dashboard.plots.theme import (
    duration_ticks, format_seconds, theme_ctx,
)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Missing submitted video duration")
    result = float(value)
    if not isfinite(result) or result < 0:
        raise ValueError("Invalid submitted video duration")
    return result


@safe_chart(height=390)
def build_today_submissions_lollipop(output, is_dark=True):
    """Render verified per-user video hours, with separate rework lollipops."""
    if not isinstance(output, dict) or not output.get('available'):
        reason = output.get('reason') if isinstance(output, dict) else None
        return state_figure(
            (reason or "Today's submitted video duration is unavailable.") +
            ' No task-status or batch-return hours were substituted.',
            is_dark, 390)
    if output.get('unit') != 'submitted_video_seconds':
        raise ValueError('Submission chart requires VIDEO duration, not task counts')

    rows = output.get('users')
    values = output.get('values')
    if not isinstance(rows, list) or not isinstance(values, dict):
        raise ValueError('Missing per-user submission video durations')
    for key in ('submitted_total', 'new', 'old_rework', 'same_day_rework'):
        _number(values.get(key))

    seen = set()
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid per-user submission row')
        name = row.get('User')
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError('Duplicate or invalid submission user')
        seen.add(name)
        submitted = _number(row.get('submitted_total'))
        new = _number(row.get('new'))
        old = _number(row.get('old_rework'))
        same = _number(row.get('same_day_rework'))
        if abs(submitted - new - old - same) > 0.05:
            raise ValueError('Submitted total does not reconcile to video-duration categories')
        parsed.append({'User': name, 'submitted': submitted,
                       'new': new, 'old': old, 'same': same})

    if any(abs(sum(row[column] for row in parsed) - values[total]) > 0.05
           for column, total in (('submitted', 'submitted_total'), ('new', 'new'),
                                 ('old', 'old_rework'), ('same', 'same_day_rework'))):
        raise ValueError('User totals disagree with verified daily submission evidence')

    if not parsed:
        return state_figure('No dated video submissions recorded for the selected users.',
                            is_dark, 390)

    parsed.sort(key=lambda row: (-row['submitted'], row['User'].casefold()))
    users = [row['User'] for row in parsed]
    x = list(range(len(parsed)))
    theme = theme_ctx(is_dark)
    line_color = '#c2fd75' if is_dark else '#126e59'
    old_color = '#f59e71' if is_dark else '#bc5f28'
    same_color = '#b6a5ff' if is_dark else '#7154bd'
    dark_edge = theme['bg_color']
    fig = go.Figure()

    totals = [row['submitted'] for row in parsed]
    # A single continuous LINE shows total paid video duration submitted by
    # each operator. Rework lollipops are already included in that line.
    fig.add_trace(go.Scatter(
        x=x, y=[value / 3600 for value in totals],
        mode='lines+markers+text', name='Submitted video',
        line={'color': line_color, 'width': 3.5, 'shape': 'linear'},
        marker={'size': 10, 'color': line_color,
                'line': {'color': dark_edge, 'width': 2}},
        text=[format_seconds(value, compact=True) for value in totals],
        textposition='top center', textfont={'size': 11, 'color': line_color},
        customdata=[[user, format_seconds(value),
                     format_seconds(row['old'] + row['same'])]
                    for user, value, row in zip(users, totals, parsed)],
        hovertemplate='<b>%{customdata[0]}</b><br>Submitted video: %{customdata[1]}'
                      '<br>Rework included: %{customdata[2]}<extra></extra>',
        showlegend=True,
    ))

    # Each rework type has a narrow STEM from zero and a visible terminal
    # marker: a real lollipop, not a second line or an extra submitted total.
    for key, label, color, offset in (
        ('old', 'Old rework', old_color, -0.16),
        ('same', 'Same-day rework', same_color, 0.16),
    ):
        points = [row[key] for row in parsed]
        xs = [number + offset for number in x]
        for px, sec in zip(xs, points):
            if sec:
                fig.add_shape(
                    type='line', x0=px, x1=px, y0=0, y1=sec / 3600,
                    xref='x', yref='y',
                    line={'color': color, 'width': 2.5},
                    layer='below')
        fig.add_trace(go.Scatter(
            x=xs, y=[value / 3600 for value in points],
            mode='markers', name=label,
            marker={'size': 12, 'color': color, 'symbol': 'circle',
                    'line': {'width': 1.5, 'color': dark_edge}},
            customdata=[[user, format_seconds(value)] for user, value in zip(users, points)],
            hovertemplate='<b>%{customdata[0]}</b><br>' + label +
                          ': %{customdata[1]}<extra></extra>',
            showlegend=True,
        ))

    upper = max(max(totals, default=0) / 3600 * 1.23, 1 / 60)
    ticks, ticklabels = duration_ticks(0, upper)
    subtitle = (
        'Today so far · submitted video duration includes old and same-day rework'
        '<br>Rework lollipops are components of Submitted, not additional hours'
    )
    if output.get('is_snapshot'):
        subtitle += ' · saved snapshot'
    if output.get('reconciliation_pending'):
        subtitle += ' · reconciliation pending'
    if output.get('capture'):
        subtitle += ' · captured ' + str(output['capture'])[:19]

    fig.update_layout(
        title={'text': "Today's submitted video duration · " + str(output['date']),
               'subtitle': {'text': subtitle, 'font': {'size': 10}}},
        template=theme['template'], height=max(390, 390 + max(0, len(users) - 9) * 10),
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        margin={'l': 72, 'r': 30, 't': 103, 'b': 96},
        showlegend=True,
        legend={'orientation': 'h', 'x': 0, 'y': -.25,
                'xanchor': 'left', 'yanchor': 'top', 'font': {'size': 11}},
        xaxis={'tickmode': 'array', 'tickvals': x, 'ticktext': users,
               'range': [-0.48, len(users) - 0.52], 'fixedrange': True,
               'showgrid': False, 'automargin': True, 'title': None},
        yaxis={'title': 'Video duration (HH:MM)', 'range': [0, upper],
               'tickmode': 'array', 'tickvals': ticks, 'ticktext': ticklabels,
               'fixedrange': True, 'zeroline': True, 'automargin': True},
        hovermode='closest', uirevision='today-video-hours-v2',
        meta={
            'metric': 'dated_submitted_video_duration',
            'unit': 'video_hours',
            'date': output['date'],
            'submitted_seconds': values['submitted_total'],
            'new_seconds': values['new'],
            'old_rework_seconds': values['old_rework'],
            'same_day_rework_seconds': values['same_day_rework'],
            'rework_is_subset': True,
            'screen_time_included': False,
            'source': output.get('source'),
            'partial': bool(output.get('reconciliation_pending')),
        },
    )
    return fig

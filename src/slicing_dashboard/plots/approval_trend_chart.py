"""Presentation of prepared daily throughput; gaps are never filled with zeros."""
import plotly.graph_objects as go

from slicing_dashboard.plots.work_trend_chart import _layout, _duration_label, _seconds
from slicing_dashboard.plots.guardrails import safe_chart, dated_records
from slicing_dashboard.reporting.approval_reports import APPROVAL_STAGES


@safe_chart(height=420)
def build_approval_trend_chart(report, is_dark=True, *, primary_only=False, primary_metric='submitted'):
    rows = dated_records((report or {}).get('rows', []))
    dates = [row['date'] for row in rows]
    figure = go.Figure()
    if primary_metric not in ('submitted', 'completed'):
        raise ValueError('Unknown primary metric')
    completed = primary_only and primary_metric == 'completed'
    primary_field = 'completed_seconds' if completed else 'total_seconds'
    series = [(primary_field, 'Completed video' if completed else 'Total Work Done')]
    colors = [('#c2fd75' if is_dark else '#165a50') if primary_only else '#38bdf8']
    if not primary_only:
        series.extend(APPROVAL_STAGES)
        colors.extend(['#a78bfa', '#fbbf24', '#34d399'])
    if not primary_only and any('completed_seconds' in row for row in rows):
        series.append(('completed_seconds', 'Completed Video (includes errors)'))
        colors.append('#fb7185')
    for (field, label), color in zip(series, colors):
        values = [_seconds(row.get(field)) for row in rows]
        available = any(value is not None for value in values)
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        figure.add_trace(go.Scatter(
            name=label if available else label + ' (unavailable)', x=dates,
            y=[value / 3600 if value is not None else None for value in values],
            customdata=[_duration_label(value) for value in values],
            mode='lines+markers', connectgaps=False,
            fill='tozeroy', fillcolor=f'rgba({rgb[0]},{rgb[1]},{rgb[2]},0.16)',
            line={'color': color, 'width': 2.5, 'shape': 'spline', 'smoothing': .65}, marker={'size': 4},
            hovertemplate=(f'<b>Team</b><br>{label}<br>'
                           + ('%{customdata}' if available else 'Duration: Unavailable')
                           + '<extra></extra>'),
        ))
    # Fresh submissions are part of the total, alongside same-day rework.
    if not primary_only and any('new_seconds' in row for row in rows):
        values = [_seconds(row.get('new_seconds')) for row in rows]
        available = any(value is not None for value in values)
        figure.add_trace(go.Scatter(
            name='New submissions' if available else 'New submissions (unavailable)',
            x=dates, y=[value / 3600 if value is not None else None for value in values],
            customdata=[_duration_label(value) for value in values],
            mode='lines+markers', connectgaps=False, fill='none',
            line={'color': '#f97316', 'width': 3, 'dash': 'dash'}, marker={'size': 5},
            hovertemplate='<b>New submissions</b><br>%{customdata}<br>First-time work; included in Total Work Done<extra></extra>',
        ))
    revision = f"approval-trend:{report.get('range_start')}:{report.get('range_end')}"
    title = 'Work and approval funnel by batch date' if report.get('cohort_funnel') else 'Daily work and approvals'
    _layout(figure, f"{title} · {report.get('range_start')} to {report.get('range_end')}",
            is_dark, revision)
    figure.update_layout(margin={'b': 150}, yaxis_title='Video hours',
                         legend={'entrywidth': 210})
    if primary_only:
        finite_values = [value for value in figure.data[0].y if value is not None]
        upper = max(finite_values, default=0)
        figure.update_traces(line={'width': 3.5}, marker={'size': 7, 'line': {'width': 1.5,
                             'color': '#030e09' if is_dark else '#ffffff'}},
                             cliponaxis=False, fill='none')
        figure.update_layout(title='Completed video duration' if completed else 'Daily work output', showlegend=False, height=420,
                             margin={'l': 70, 'r': 28, 't': 56, 'b': 56},
                             yaxis={'range': [0, upper * 1.2 if upper else 1], 'autorange': False},
                             xaxis_title='Source date · UTC+08' if completed else None, hovermode='closest')
        figure.update_layout(meta={'chart_role': 'primary-trend', 'recorded_days': len(finite_values),
                                  'primary_metric': primary_metric})
    if not any(row.get(primary_field) is not None for row in rows):
        figure.add_annotation(text='No recorded completed video for this period.' if completed else 'No recorded submissions for this period.',
                              x=.5, y=.5, xref='paper', yref='paper', showarrow=False)
    return figure

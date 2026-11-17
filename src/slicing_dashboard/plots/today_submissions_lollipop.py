"""Today-only lollipop of dated submitted VIDEO duration, not labor hours."""
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart, state_figure
from slicing_dashboard.plots.theme import format_seconds, theme_ctx


ORDER = (
    ('submitted_total', 'Submitted today'),
    ('new', 'New videos'),
    ('old_rework', 'Old rework'),
    ('same_day_rework', 'Same-day rework'),
)


@safe_chart(height=360)
def build_today_submissions_lollipop(output, is_dark=True):
    if not isinstance(output, dict) or not output.get('available'):
        reason = (output or {}).get('reason') if isinstance(output, dict) else None
        return state_figure(
            (reason or 'Today’s verified video submissions are unavailable.') +
            ' Return events and batch approvals are not substituted.', is_dark, 360)
    values = output['values']
    counts = output['counts']
    total = float(values['submitted_total'])
    components = sum(float(values[key]) for key in ('new', 'old_rework', 'same_day_rework'))
    if abs(total - components) > max(1e-5, total * 1e-12):
        raise ValueError('Submitted video total does not reconcile to components')
    theme = theme_ctx(is_dark)
    colors = (['#c2fd75', '#43b8c6', '#a78bfa', '#f5ba6b'] if is_dark
              else ['#165a50', '#0891b2', '#8b5cf6', '#c46c1e'])
    figure = go.Figure()
    for index, (key, name) in enumerate(ORDER):
        seconds = float(values[key])
        hours = seconds / 3600
        color = colors[index]
        count = counts.get(key)
        label = format_seconds(seconds)
        figure.add_shape(type='line', x0=0, x1=hours, y0=name, y1=name,
                         xref='x', yref='y', line={'color': color, 'width': 4})
        figure.add_trace(go.Scatter(
            x=[hours], y=[name], mode='markers',
            marker={'size': 17 if index == 0 else 14,
                    'color': color, 'line': {'width': 2, 'color': theme['bg_color']}},
            customdata=[[label, count if count is not None else 'Unavailable']],
            hovertemplate=('<b>' + name + '</b><br>Submitted video: %{customdata[0]}'
                           '<br>Tasks: %{customdata[1]}<extra></extra>'),
            showlegend=False, name=name,
        ))
        figure.add_annotation(x=hours, y=name, xshift=14, xanchor='left',
                              text=label, showarrow=False, xref='x', yref='y',
                              font={'size': 11, 'color': theme['font_color']})
    capture = output.get('capture')
    caution = 'Today so far · captured submissions only'
    if output.get('is_snapshot'):
        caution += ' · saved snapshot'
    if output.get('reconciliation_pending'):
        caution += ' · reconciliation pending'
    if capture:
        caution += ' · captured ' + str(capture)[:19]
    figure.update_layout(
        title={'text': f"Today’s submitted video · {output['date']}",
               'subtitle': {'text': caution +
                  '<br>Total includes New + Old rework + Same-day rework'
                  ' · Video output, not time worked',
                  'font': {'size': 10}}},
        template=theme['template'], height=360,
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        margin={'l': 132, 'r': 110, 't': 92, 'b': 32},
        showlegend=False,
        xaxis={'title': 'Submitted video hours', 'range': [0, max(1, total / 3600 * 1.30)],
               'rangemode': 'tozero', 'fixedrange': True},
        yaxis={'categoryorder': 'array',
               'categoryarray': [label for _, label in ORDER],
               'autorange': 'reversed', 'fixedrange': True},
        uirevision='today-submitted-video-v1',
        meta={'metric': 'submitted_video_seconds',
              'date': output['date'],
              'component_seconds': {key: float(values[key]) for key, _ in ORDER},
              'actual_labor_seconds': None,
              'reconciled': True,
              'source': output.get('source')},
    )
    return figure

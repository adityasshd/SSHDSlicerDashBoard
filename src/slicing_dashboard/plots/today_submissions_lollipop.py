"""Today's evidence-backed counts of submitted tasks and rework submissions.

Rework submissions are a subset of submitted tasks. Neither value is a
batch-return event count, current status count, video hours, or labor time.
"""
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart, state_figure
from slicing_dashboard.plots.theme import theme_ctx


ORDER = (
    ('submitted_total', 'Submitted today'),
    ('rework_total', 'Rework submissions'),
)


@safe_chart(height=300)
def build_today_submissions_lollipop(output, is_dark=True):
    if not isinstance(output, dict) or not output.get('available'):
        reason = (output or {}).get('reason') if isinstance(output, dict) else None
        return state_figure(
            (reason or "Today's verified task-submission counts are unavailable.") +
            ' Return events and current batch status are not substituted.',
            is_dark, 300)

    counts = output.get('counts') or {}
    total = counts.get('submitted_total')
    rework = counts.get('rework_total')
    if any(type(value) is not int or value < 0 for value in (total, rework)):
        raise ValueError('Missing or invalid verified task counts')
    if rework > total:
        raise ValueError('Rework submissions exceed submitted tasks')

    theme = theme_ctx(is_dark)
    colors = (['#c2fd75', '#a78bfa'] if is_dark
              else ['#165a50', '#8b5cf6'])
    figure = go.Figure()
    for index, (key, label) in enumerate(ORDER):
        count = counts[key]
        color = colors[index]
        figure.add_shape(
            type='line', x0=0, x1=count, y0=label, y1=label,
            xref='x', yref='y', line={'color': color, 'width': 4})
        figure.add_trace(go.Scatter(
            x=[count], y=[label], mode='markers',
            marker={'size': 17 if index == 0 else 15,
                    'color': color,
                    'line': {'width': 2, 'color': theme['bg_color']}},
            customdata=[[count]],
            hovertemplate='<b>' + label + '</b><br>%{customdata[0]} task submissions<extra></extra>',
            showlegend=False, name=label))
        figure.add_annotation(
            x=count, y=label, xshift=14, xanchor='left',
            text=str(count), showarrow=False, xref='x', yref='y',
            font={'size': 12, 'color': theme['font_color']})

    note = ('Today so far · verified dated task submissions'
            '<br>Rework submissions are included in Submitted today; '
            'the two rows must not be added')
    if output.get('is_snapshot'):
        note += ' · saved snapshot'
    if output.get('reconciliation_pending'):
        note += ' · reconciliation pending'
    if output.get('capture'):
        note += ' · captured ' + str(output['capture'])[:19]

    figure.update_layout(
        title={'text': f"Today's submissions · {output['date']}",
               'subtitle': {'text': note, 'font': {'size': 10}}},
        template=theme['template'], height=300,
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        margin={'l': 150, 'r': 75, 't': 94, 'b': 35},
        showlegend=False,
        xaxis={'title': 'Tasks submitted', 'range': [0, max(1, total * 1.28)],
               'rangemode': 'tozero', 'fixedrange': True, 'tickformat': ',d'},
        yaxis={'categoryorder': 'array',
               'categoryarray': [label for _, label in ORDER],
               'autorange': 'reversed', 'fixedrange': True},
        uirevision='today-task-count-v1',
        meta={'metric': 'dated_task_submission_count',
              'unit': 'tasks',
              'date': output['date'],
              'submitted_count': total,
              'rework_count': rework,
              'rework_is_subset': True,
              'video_hours_inferred': False,
              'source': output.get('source')},
    )
    return figure

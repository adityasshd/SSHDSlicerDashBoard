"""Compact observed month-to-date return-event history chart."""
from datetime import date

import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart, state_figure
from slicing_dashboard.plots.theme import theme_ctx


@safe_chart(height=355)
def build_monthly_returns_chart(report, is_dark=True):
    """Daily *event* counts by latest status, never hours or reviewer identity."""
    if not isinstance(report, dict) or report.get('coverage') != 'observed_return_events_only':
        return state_figure('Observed return history unavailable.', is_dark, 355)
    rows = report.get('daily') or []
    if not rows:
        return state_figure('No monthly return records available.', is_dark, 355)
    palette = (
        {'Completed': '#c2fd75', 'Pending Review': '#a78bfa',
         'Other / Unlinked': '#64748b'}
        if is_dark else
        {'Completed': '#165a50', 'Pending Review': '#8b5cf6',
         'Other / Unlinked': '#94a3b8'}
    )
    theme = theme_ctx(is_dark)
    figure = go.Figure()
    for state in ('Completed', 'Pending Review', 'Other / Unlinked'):
        counts = [int(row.get(state, 0)) for row in rows]
        figure.add_trace(go.Bar(
            x=[row['date'] for row in rows],
            y=counts, name=state,
            marker={'color': palette[state]},
            customdata=[row['date'] for row in rows],
            hovertemplate=('<b>%{customdata}</b><br>' + state +
                           ': %{y} observed returns<extra></extra>'),
        ))
    month = date.fromisoformat(report['start']).strftime('%B %Y')
    total = report['summary']['observed_returns']
    figure.update_layout(
        title={'text': f'{month} · observed batch returns',
               'subtitle': {'text': f'{total} dated return events · latest batch state, not status at return time'
                            '<br>Saved evidence only; incomplete lifetime history possible',
                            'font': {'size': 10}}},
        template=theme['template'], height=355, barmode='stack', bargap=.30,
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'color': theme['font_color']},
        margin={'l': 60, 'r': 20, 't': 90, 'b': 42},
        xaxis={'type': 'date', 'tickformat': '%d %b', 'dtick': 2 * 86400000,
               'title': None, 'fixedrange': True},
        yaxis={'title': 'Observed return events', 'rangemode': 'tozero',
               'dtick': 10 if max(row.get('total', 0) for row in rows) > 20 else 1,
               'fixedrange': True},
        legend={'orientation': 'h', 'y': -0.25, 'x': .02},
        hovermode='x unified',
        meta={'metric': 'observed_return_event_count',
              'status_basis': 'latest_batch_status',
              'coverage': report['coverage'],
              'date_start': report['start'], 'date_end': report['end'],
              'total_observed': total,
              'completed_state_returns': report['summary']['completed_state_returns'],
              'pending_review_state_returns': report['summary']['pending_review_state_returns'],
              'other_unlinked_returns': report['summary']['other_or_unlinked_returns']},
    )
    return figure

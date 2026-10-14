"""Stage outcomes for the same selected batch cohort."""
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart
from slicing_dashboard.plots.work_trend_chart import _layout, _duration_label
from slicing_dashboard.reporting.approval_funnel import STAGES


@safe_chart(height=380)
def build_approval_outcomes_chart(totals, is_dark=True, available=True, start=None, end=None):
    figure = go.Figure()
    if available:
        for outcome, color in (
            ('Approved', '#34d399'), ('Rejected / returned', '#fb7185'),
            ('Awaiting review', '#fbbf24'), ('Not reached', '#64748b'), ('Unknown', '#a78bfa'),
        ):
            values = [totals[stage][outcome] for stage in STAGES]
            figure.add_trace(go.Bar(
                name=outcome, x=list(STAGES),
                y=[None if value['missing'] else value['seconds'] / 3600 for value in values],
                marker_color=color,
                customdata=[[value['count'], _duration_label(None if value['missing'] else value['seconds']),
                             value['missing']] for value in values],
                hovertemplate=('<b>%{x}</b><br>' + outcome + '<br>Content: %{customdata[1]}'
                               '<br>Batches: %{customdata[0]}<br>Missing durations: %{customdata[2]}<extra></extra>'),
            ))
    else:
        figure.add_annotation(text='Approval cohort unavailable. Refresh to retry.', x=.5, y=.5,
                              xref='paper', yref='paper', showarrow=False)
    _layout(figure, f'Approval and rejection outcomes · {start or ""} to {end or ""}',
            is_dark, f'approval-outcomes:{start}:{end}')
    figure.update_layout(barmode='stack', height=380, yaxis_title='Batch content hours',
                         xaxis={'type': 'category', 'title': 'Review stage', 'tickformat': None,
                                'tickangle': 0, 'categoryorder': 'array', 'categoryarray': list(STAGES)},
                         yaxis={'tickmode': 'auto', 'tickvals': None, 'ticktext': None},
                         legend={'entrywidth': 135}, margin={'b': 100})
    return figure

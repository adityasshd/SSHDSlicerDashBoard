"""Completed video duration per user, shown as a lollipop chart."""
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import checked_frame, pad_hour_axis, safe_chart, state_figure, hour_total_label
from slicing_dashboard.plots.theme import CHART_HEIGHT, format_seconds, theme_ctx, user_color


@safe_chart
def build_individual_chart(breakdown_df, start_date: str, end_date: str, is_dark: bool) -> go.Figure:
    """Keep one selectable endpoint per user and a thin stem from zero."""
    theme = theme_ctx(is_dark)
    frame = checked_frame(breakdown_df, ['User', 'Completed Duration'], ['Completed Duration'])
    if frame.empty:
        return state_figure('No completed work for this period.', is_dark)
    rows = frame.groupby('User', as_index=False)['Completed Duration'].sum(min_count=1)
    rows = rows.sort_values(['Completed Duration', 'User'], ascending=[False, True])
    figure = go.Figure()
    for user, seconds in rows.itertuples(index=False, name=None):
        hours, color = seconds / 3600, user_color(user)
        figure.add_shape(type='line', x0=user, x1=user, y0=0, y1=hours,
                         line={'color': color, 'width': 3}, layer='below')
        figure.add_trace(go.Scatter(
            name=user, x=[user], y=[hours], mode='markers+text',
            marker={'color': color, 'size': 13, 'line': {'color': color, 'width': 2}},
            text=[hour_total_label(hours)], textposition='top center', cliponaxis=False,
            textfont={'size': 10}, customdata=[[format_seconds(seconds)]],
            hovertemplate='<b>%{x}</b><br>Completed<br>%{customdata[0]}<extra></extra>',
        ))
    figure.update_layout(
        title='Completed video duration', template=theme['template'],
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        height=CHART_HEIGHT, margin={'l': 40, 'r': 20, 't': 48, 'b': 40},
        xaxis={'title': '', 'showgrid': False, 'categoryorder': 'array', 'categoryarray': list(rows.User)},
        yaxis={'title': 'Hours', 'showgrid': True},
        clickmode='event+select', hovermode='closest', showlegend=False,
    )
    return pad_hour_axis(figure)

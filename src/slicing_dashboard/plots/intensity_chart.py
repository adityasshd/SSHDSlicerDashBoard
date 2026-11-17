"""Compact user-by-category duration heatmaps with optional count labels."""
from html import escape

import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from slicing_dashboard.plots.theme import theme_ctx, tooltip_text_color


def intensity_chart(users, categories, metrics, customdata, hovertemplate, title, is_dark,
                    subtitle=None, show_counts=False):
    """Keep intensity in hours; optionally label each cell as HH:MM / count."""
    theme = theme_ctx(is_dark)
    scale = ([[0, '#0d211c'], [.5, '#165a50'], [1, '#c2fd75']] if is_dark else
             [[0, '#edf5ed'], [.5, '#a9d89b'], [1, '#165a50']])
    values, labels = metrics['Hours']
    counts = next(matrix[0] for label, matrix in metrics.items() if label != 'Hours')
    has_total = bool(users and users[-1] == '<b>Total</b>')
    colored_values = values[:-1] if has_total else values
    maximum = max((value for row in colored_values for value in row if value is not None), default=0) or 1
    neutral = '#17251f' if is_dark else '#eef1ef'
    annotations, hover_colors, hover_text_colors = [], [], []
    for user, row, texts, count_row in zip(users, values, labels, counts):
        row_colors, row_text_colors = [], []
        for category, value, text, count in zip(categories, row, texts, count_row):
            color = (neutral if has_total and user == users[-1] else
                     sample_colorscale(scale, [value / maximum])[0] if value is not None else None)
            row_colors.append(color or ('#10261e' if is_dark else '#ffffff'))
            row_text_colors.append(tooltip_text_color(row_colors[-1]))
            if show_counts:
                text += f' / {int(count) if count is not None else "—"}'
            annotations.append(dict(
                x=category, y=user, xref='x', yref='y', text=escape(text), showarrow=False,
                font={'size': 11, 'color': tooltip_text_color(color) if color else theme['font_color']},
            ))
        hover_colors.append(row_colors)
        hover_text_colors.append(row_text_colors)
    figure = go.Figure(go.Heatmap(
        x=categories, y=users[:-1] if has_total else users, z=colored_values,
        customdata=customdata[:-1] if has_total else customdata,
        zmin=0, zmax=maximum, colorscale=scale, xgap=4, ygap=4,
        showscale=False,
        hovertemplate=hovertemplate, hoverongaps=True,
        hoverlabel={'bgcolor': hover_colors[:-1] if has_total else hover_colors,
                    'bordercolor': hover_colors[:-1] if has_total else hover_colors,
                    'font': {'size': 12, 'color': hover_text_colors[:-1] if has_total else hover_text_colors}},
    ))
    if has_total:
        figure.add_trace(go.Heatmap(
            x=categories, y=users[-1:], z=values[-1:], customdata=customdata[-1:],
            colorscale=[[0, neutral], [1, neutral]], showscale=False, xgap=4, ygap=4,
            hovertemplate=hovertemplate, hoverongaps=True,
            hoverlabel={'bgcolor': neutral, 'bordercolor': neutral,
                        'font': {'color': theme['font_color']}},
            name='Total',
        ))
    figure.update_layout(
        title={'text': title, 'subtitle': {'text': subtitle or '', 'font': {'size': 10}}},
        template=theme['template'], paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        height=max(340, len(users) * 30 + 150),
        margin={'l': 70, 'r': 16, 't': 88, 'b': 24},
        xaxis={'showgrid': False, 'side': 'top', 'type': 'category', 'fixedrange': True},
        yaxis={'showgrid': False, 'autorange': 'reversed', 'type': 'category', 'fixedrange': True,
               'categoryorder': 'array', 'categoryarray': users},
        annotations=annotations, showlegend=False, hovermode='closest',
        meta={'intensity_matrix': True, 'show_counts': bool(show_counts),
              'column_totals': values[-1] if has_total else None},
    )
    return figure

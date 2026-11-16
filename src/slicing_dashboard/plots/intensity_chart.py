"""Compact user-by-category duration heatmaps with optional count labels."""
from html import escape

import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from slicing_dashboard.plots.theme import duration_ticks, theme_ctx, tooltip_text_color


def intensity_chart(users, categories, metrics, customdata, hovertemplate, title, is_dark,
                    subtitle=None, show_counts=False):
    """Keep intensity in hours; optionally label each cell as HH:MM / count."""
    theme = theme_ctx(is_dark)
    scale = ([[0, '#0d211c'], [.5, '#165a50'], [1, '#c2fd75']] if is_dark else
             [[0, '#edf5ed'], [.5, '#a9d89b'], [1, '#165a50']])
    values, labels = metrics['Hours']
    counts = next(matrix[0] for label, matrix in metrics.items() if label != 'Hours')
    maximum = max((value for row in values for value in row if value is not None), default=0) or 1
    annotations, hover_colors, hover_text_colors = [], [], []
    for user, row, texts, count_row in zip(users, values, labels, counts):
        row_colors, row_text_colors = [], []
        for category, value, text, count in zip(categories, row, texts, count_row):
            color = sample_colorscale(scale, [value / maximum])[0] if value is not None else None
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
    ticks, texts = duration_ticks(0, maximum)
    figure = go.Figure(go.Heatmap(
        x=categories, y=users, z=values, customdata=customdata,
        zmin=0, zmax=maximum, colorscale=scale, xgap=4, ygap=4,
        colorbar=dict(title={'text': 'Duration (HH:MM)', 'side': 'bottom'},
                      orientation='h', x=0, xanchor='left', y=0, yanchor='top',
                      ypad=16, len=1, thickness=7, outlinewidth=0,
                      tickmode='array', tickvals=ticks, ticktext=texts),
        hovertemplate=hovertemplate, hoverongaps=True,
        hoverlabel={'bgcolor': hover_colors, 'bordercolor': hover_colors,
                    'font': {'size': 12, 'color': hover_text_colors}},
    ))
    figure.update_layout(
        title={'text': title, 'subtitle': {'text': subtitle or '', 'font': {'size': 10}}},
        template=theme['template'], paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        height=max(340, len(users) * 30 + 150),
        margin={'l': 70, 'r': 16, 't': 88, 'b': 90},
        xaxis={'showgrid': False, 'side': 'top', 'type': 'category', 'fixedrange': True},
        yaxis={'showgrid': False, 'autorange': 'reversed', 'type': 'category', 'fixedrange': True},
        annotations=annotations, showlegend=False, hovermode='closest',
        meta={'intensity_matrix': True, 'show_counts': bool(show_counts)},
    )
    return figure

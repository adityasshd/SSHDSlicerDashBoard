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
    # Each column measures its own relative intensity. A large value in one
    # return tier must not flatten the colors in a different tier. Preserve
    # actual hour values in each trace (do not replace z with normalized data).
    column_maxima = [
        max((float(row[index]) for row in colored_values
             if row[index] is not None), default=0.0)
        for index in range(len(categories))
    ]
    color_limits = [peak if peak > 0 else 1.0 for peak in column_maxima]
    neutral = '#17251f' if is_dark else '#eef1ef'
    annotations, hover_colors, hover_text_colors = [], [], []
    for user, row, texts, count_row in zip(users, values, labels, counts):
        row_colors, row_text_colors = [], []
        for index, (category, value, text, count) in enumerate(zip(categories, row, texts, count_row)):
            color = (neutral if has_total and user == users[-1] else
                     sample_colorscale(scale, [value / color_limits[index]])[0]
                     if value is not None else None)
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
    # Plotly permits only one z-range for each Heatmap trace. Render one
    # trace per category, each at its own zmax, so z stays in real hours and
    # hover details / count annotations remain unchanged. A separate neutral
    # Total trace below is deliberately not part of any column scale.
    figure = go.Figure()
    detail_users = users[:-1] if has_total else users
    detail_custom = customdata[:-1] if has_total else customdata
    detail_colors = hover_colors[:-1] if has_total else hover_colors
    detail_text_colors = hover_text_colors[:-1] if has_total else hover_text_colors
    for index, category in enumerate(categories):
        colors = [[row[index]] for row in detail_colors]
        text_colors = [[row[index]] for row in detail_text_colors]
        figure.add_trace(go.Heatmap(
            x=[category], y=detail_users,
            z=[[row[index]] for row in colored_values],
            customdata=[[row[index]] for row in detail_custom],
            zmin=0, zmax=color_limits[index], colorscale=scale,
            xgap=4, ygap=4, showscale=False,
            hovertemplate=hovertemplate, hoverongaps=True,
            hoverlabel={'bgcolor': colors, 'bordercolor': colors,
                        'font': {'size': 12, 'color': text_colors}},
            name=category,
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
              'color_scope': 'per_column',
              'column_maxima': column_maxima,
              'column_totals': values[-1] if has_total else None},
    )
    return figure

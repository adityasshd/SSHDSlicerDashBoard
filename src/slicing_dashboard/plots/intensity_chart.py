"""Compact user-by-category duration heatmaps with optional count labels."""
from html import escape

import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from slicing_dashboard.plots.theme import theme_ctx, tooltip_text_color


def intensity_chart(users, categories, metrics, customdata, hovertemplate, title, is_dark,
                    subtitle=None, show_counts=False, value_key='Hours'):
    """Keep intensity in hours; optionally label each cell as HH:MM / count."""
    theme = theme_ctx(is_dark)
    scale = ([[0, '#0d211c'], [.5, '#165a50'], [1, '#c2fd75']] if is_dark else
             [[0, '#edf5ed'], [.5, '#a9d89b'], [1, '#165a50']])
    # Charts may show original video hours or observed batch counts. Never
    # normalize a duration when the visible metric is a count.
    values, labels = metrics[value_key]
    counts = metrics['Batches'][0] if 'Batches' in metrics else values
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
    # One aligned matrix is essential: Plotly's per-trace auto-cell widths
    # for single-column Heatmaps and a single-row Total trace can detach the
    # colored rectangles from the category labels (visible production bug).
    # Independently normalize *only the color coordinate*, preserving exact
    # real hours at the last customdata position and in column_totals.
    normalized = [
        [(float(value) / color_limits[index] if value is not None else None)
         for index, value in enumerate(row)]
        for row in values
    ]
    custom_with_raw_hours = [
        [[*cell, value] for cell, value in zip(custom_row, raw_row)]
        for custom_row, raw_row in zip(customdata, values)
    ]
    if has_total:
        # Reserve the negative color-space for an explicit neutral Total row,
        # rather than introducing a second trace with mismatched cell bounds.
        normalized[-1] = [-1.0] * len(categories)
        display_scale = [
            [0.0, neutral], [0.4999, neutral],
            [0.5, scale[0][1]], [0.75, scale[1][1]], [1.0, scale[2][1]],
        ]
    else:
        display_scale = scale
    figure = go.Figure(go.Heatmap(
        x=categories, y=users, z=normalized, customdata=custom_with_raw_hours,
        zmin=-1 if has_total else 0, zmax=1, colorscale=display_scale,
        xgap=4, ygap=4, showscale=False,
        hovertemplate=hovertemplate, hoverongaps=True,
        hoverlabel={'bgcolor': hover_colors, 'bordercolor': hover_colors,
                    'font': {'size': 12, 'color': hover_text_colors}},
    ))
    figure.update_layout(
        title=({'text': title} if subtitle == '' else
               {'text': title, 'subtitle': {
                   'text': ((subtitle + ' · ') if subtitle else '') + 'Color intensity relative within each column',
                   'font': {'size': 10}}}),
        template=theme['template'], paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        height=max(340, len(users) * 30 + 150),
        margin={'l': 70, 'r': 16, 't': 58 if subtitle == '' else 88, 'b': 24},
        xaxis={'showgrid': False, 'side': 'top', 'type': 'category', 'fixedrange': True},
        yaxis={'showgrid': False, 'autorange': 'reversed', 'type': 'category', 'fixedrange': True,
               'categoryorder': 'array', 'categoryarray': users},
        annotations=annotations, showlegend=False, hovermode='closest',
        meta={'intensity_matrix': True, 'show_counts': bool(show_counts),
              'color_scope': 'per_column',
              'single_aligned_matrix': True,
              'raw_hour_customdata_index': -1 if value_key == 'Hours' else None,
              'raw_value_customdata_index': -1,
              'value_unit': value_key,
              'column_maxima': column_maxima,
              'column_totals': values[-1] if has_total else None},
    )
    return figure

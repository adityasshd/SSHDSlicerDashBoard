"""Shared chart validation and presentation boundaries; invalid is never zero."""
from functools import wraps
from inspect import signature
import logging
from math import isfinite
from textwrap import wrap
from html import escape

import pandas as pd
import plotly.graph_objects as go

from slicing_dashboard.plots.theme import CHART_HEIGHT, theme_ctx, format_seconds, duration_ticks, tooltip_text_color

log = logging.getLogger(__name__)


def hour_total_label(hours):
    """Compact elapsed time for chart totals."""
    value = finite_number(hours)
    if value is None:
        return ''
    return format_seconds(value * 3600, compact=value == 0 or value >= 1 / 60)


def pad_hour_axis(figure, orientation='v'):
    """Reserve ten percent beyond the tallest stack or other visible hour series."""
    coordinate = 'x' if orientation == 'h' else 'y'
    totals = {}
    maximum = 0.
    for trace in figure.data:
        if trace.visible is False or trace.visible == 'legendonly':
            continue
        values = getattr(trace, coordinate, None)
        categories = getattr(trace, 'y' if orientation == 'h' else 'x', None)
        if values is None:
            continue
        for index, value in enumerate(values):
            number = finite_number(value)
            if number is None:
                continue
            maximum = max(maximum, number)
            if trace.type == 'bar' and figure.layout.barmode in ('stack', 'relative') and categories is not None:
                key = categories[index]
                totals[key] = totals.get(key, 0.) + number
    maximum = max([maximum, *totals.values()])
    upper = maximum * 1.1 if maximum > 0 else 1.
    if not isfinite(upper):
        raise ValueError('Hour axis exceeds the supported numeric range')
    getattr(figure.layout, coordinate + 'axis').update(range=[0, upper], autorange=False)
    figure.update_layout(meta={**(figure.layout.meta or {}), 'hour_axis_orientation': orientation})
    return figure


def add_bar_total_labels(figure, orientation='v', count_index=None):
    """Label each visible stack once, excluding independent marker/line series."""
    totals, counts = {}, {}
    for trace in figure.data:
        if trace.type != 'bar' or trace.visible is False or trace.visible == 'legendonly':
            continue
        categories = trace.y if orientation == 'h' else trace.x
        values = trace.x if orientation == 'h' else trace.y
        for index, (category, value) in enumerate(zip(categories, values)):
            number = finite_number(value)
            previous = totals.get(category, 0.)
            totals[category] = previous + number if previous is not None and number is not None else None
            if count_index is not None:
                count = finite_number(trace.customdata[index][count_index])
                previous_count = counts.get(category, 0.)
                counts[category] = previous_count + count if previous_count is not None and count is not None else None
    if not totals:
        return figure
    for category, total in totals.items():
        if total is None:
            continue
        label = hour_total_label(total)
        if count_index is not None:
            label += f' / {int(counts[category]) if counts[category] is not None else "—"}'
        figure.add_annotation(name='bar-hour-total', text=label,
            x=total if orientation == 'h' else category,
            y=category if orientation == 'h' else total,
            xref='x', yref='y', showarrow=False,
            xanchor='left' if orientation == 'h' else 'center',
            yanchor='middle' if orientation == 'h' else 'bottom',
            xshift=6 if orientation == 'h' else 0, yshift=0 if orientation == 'h' else 6,
            font={'size': 11, 'color': figure.layout.font.color})
    if orientation == 'h':
        figure.update_layout(margin={'r': max(95 if count_index is not None else 60, figure.layout.margin.r or 0)})
    figure.update_layout(meta={**(figure.layout.meta or {}), 'bar_total_labels': orientation})
    if count_index is not None:
        figure.update_layout(meta={**figure.layout.meta, 'bar_count_index': count_index})
    return pad_hour_axis(figure, orientation)


def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) and number >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def state_figure(message='No data available for this period.', is_dark=True, height=CHART_HEIGHT):
    theme = theme_ctx(is_dark)
    figure = go.Figure()
    figure.update_layout(template=theme['template'], paper_bgcolor=theme['bg_color'],
        plot_bgcolor=theme['bg_color'], font={'color': theme['font_color'], 'family': 'Inter, sans-serif'},
        height=height, autosize=True, margin={'l': 16, 'r': 16, 't': 24, 'b': 24},
        xaxis={'visible': False}, yaxis={'visible': False})
    figure.add_annotation(text='<br>'.join(wrap(message, 36)), x=.5, y=.5,
                          xref='paper', yref='paper', showarrow=False, font={'size': 13})
    return figure


def checked_frame(frame, required, numeric=()):
    """Reject ambiguous categorical totals instead of dropping rows or inventing zeros."""
    if frame is None:
        return pd.DataFrame(columns=required)
    if not isinstance(frame, pd.DataFrame):
        raise ValueError('Invalid chart dataset')
    if frame.empty:
        return frame
    if any(column not in frame for column in required):
        raise ValueError('Missing chart columns')
    result = frame.copy()
    for column in numeric:
        if column in result:
            values = result[column].map(finite_number)
            if values.isna().any():
                raise ValueError('Invalid chart values')
            result[column] = values
    for column in ('User', 'Stage'):
        if column in result and (result[column].isna().any() or result[column].astype(str).str.strip().eq('').any()):
            raise ValueError('Missing chart labels')
    return result


def dated_records(rows, identity=()):
    """Dates are daily keys; conflicting duplicates cannot silently overwrite a person/day."""
    result, seen = [], {}
    for row in rows or []:
        value = row.get('date')
        try:
            # Daily reporting expects ISO calendar dates, not local timestamp conversion.
            from datetime import date
            day = date.fromisoformat(str(value)).isoformat()
        except (TypeError, ValueError):
            raise ValueError('Invalid chart date') from None
        key = (day, *(row.get(field) for field in identity))
        if key in seen:
            if seen[key] != row:
                raise ValueError('Conflicting duplicate daily record')
            continue
        seen[key] = row
        result.append({**row, 'date': day})
    return sorted(result, key=lambda row: row['date'])


def finish_chart(figure, is_dark=None):
    """Contain labels and legends without changing underlying coordinates/values."""
    if not isinstance(figure, go.Figure):
        return figure
    if is_dark is not None:
        figure.update_layout(font={'family': 'Segoe UI, Arial, sans-serif', 'color': theme_ctx(is_dark)['font_color']})
    figure.update_layout(autosize=True, width=None, hoverlabel={'namelength': -1, 'bordercolor': 'rgba(148,163,184,.25)'},
                         uniformtext={'minsize': 9, 'mode': 'hide'})
    if any(trace.type == 'bar' for trace in figure.data):
        figure.update_layout(bargap=max(.42, figure.layout.bargap or 0), bargroupgap=.18,
                             barcornerradius=7)
    for trace in figure.data:
        # Match native tooltips to their segment; the bounded overlay uses these colors too.
        if trace.type in ('bar', 'scatter', 'pie', 'funnel'):
            marker = trace.marker
            colors = marker.colors if trace.type == 'pie' else marker.color
            if isinstance(colors, str):
                trace.update(hoverlabel={'bgcolor': colors, 'bordercolor': colors,
                                        'font_color': tooltip_text_color(colors)})
            elif colors is not None and all(isinstance(color, str) for color in colors):
                trace.update(hoverlabel={'bgcolor': list(colors), 'bordercolor': list(colors),
                                        'font_color': [tooltip_text_color(color) for color in colors]})
        if trace.type == 'scatter' and 'lines' in (trace.mode or ''):
            trace.update(line={'shape': 'spline', 'smoothing': .65})
    figure.update_xaxes(automargin=True, zeroline=False, tickfont={'size': 12})
    figure.update_yaxes(automargin=True, zeroline=False, tickfont={'size': 12})
    for axis in figure.select_xaxes():
        if axis.showgrid is not False:
            axis.gridcolor = 'rgba(148,163,184,.16)'
    for axis in figure.select_yaxes():
        if axis.showgrid is not False:
            axis.gridcolor = 'rgba(148,163,184,.16)'
    if figure.layout.title.text:
        lines = [part for line in figure.layout.title.text.split('<br>')
                 for part in wrap(line, 38)]
        figure.update_layout(title={'text': '<br>'.join(lines), 'automargin': False,
                                    'font': {'size': 14, 'weight': 600},
                                    'yref': 'container', 'y': 1, 'yanchor': 'top', 'pad': {'t': 16}},
                             margin={'t': max(28 + 20 * len(lines), figure.layout.margin.t or 0)})
    for annotation in figure.layout.annotations or ():
        if annotation.xref == 'paper' and annotation.yref == 'paper' and annotation.text:
            annotation.text = '<br>'.join(part for line in annotation.text.split('<br>')
                                         for part in wrap(line, 30))
    # A unified tooltip for dozens of people can exceed the viewport height.
    if len(figure.data) > 8:
        figure.update_layout(hovermode='closest')
    legend_visible = figure.layout.showlegend is not False and any(
        trace.showlegend is not False and trace.name for trace in figure.data)
    if legend_visible:
        figure.update_layout(legend={'orientation': 'h', 'x': 0, 'xanchor': 'left',
                                    'y': -.22, 'yanchor': 'top', 'font': {'size': 11},
                                    'entrywidth': 110, 'maxheight': .35, 'title': {'text': ''}},
                             margin={'b': max(100, figure.layout.margin.b or 0)})
    for axis_name in ('x', 'y'):
        axis = getattr(figure.layout, axis_name + 'axis')
        if axis.type == 'date' or axis.ticktext is not None or axis.visible is False:
            continue
        categories = list(dict.fromkeys(str(value) for trace in figure.data
            for value in (getattr(trace, axis_name, None) if getattr(trace, axis_name, None) is not None else [])
            if isinstance(value, str)))
        if categories:
            # Limit ticks, never points. Exact names stay in hovers and the data table.
            stride = max(1, (len(categories) + 11) // 12) if axis_name == 'x' else 1
            ticks = categories[::stride]
            axis.update(tickmode='array', tickvals=ticks,
                        ticktext=[value if len(value) <= 16 else value[:15] + '…' for value in ticks],
                        automargin=True)
    def trace_values(trace):
        key = 'values' if trace.type == 'pie' else 'x' if trace.type == 'funnel' or getattr(trace, 'orientation', None) == 'h' else 'y'
        values = getattr(trace, key, None)
        return [] if values is None else values
    has_numeric_values = any(finite_number(value) is not None for trace in figure.data
                            if trace.type != 'heatmap' for value in trace_values(trace))
    intentional_calendar = any(trace.type == 'heatmap' for trace in figure.data)
    if not figure.data or (not has_numeric_values and figure.layout.annotations and not intentional_calendar):
        figure.update_xaxes(visible=False)
        figure.update_yaxes(visible=False)
        if not figure.layout.annotations:
            figure.add_annotation(text='No data available for this period.', x=.5, y=.5,
                                  xref='paper', yref='paper', showarrow=False)
    # Prevent unbounded SVG text from widening the tooltip. Custom data remains intact.
    for trace in figure.data:
        if trace.type == 'bar':
            trace.update(constraintext='inside', cliponaxis=trace.textposition != 'outside', marker_line_width=0)
            if getattr(trace, 'orientation', None) == 'h' and (figure.layout.meta or {}).get('bar_total_labels'):
                trace.update(textposition='none')
        if trace.name and len(trace.name) > 22:
            trace.name = '<br>'.join(escape(part) for part in wrap(trace.name, 22))
        template = getattr(trace, 'hovertemplate', None)
        for coordinate in ('x', 'y'):
            values = getattr(trace, coordinate, None)
            if template and isinstance(template, str) and '%{' + coordinate + '}' in template and values is not None:
                if all(isinstance(value, str) for value in values):
                    trace.hovertext = ['<br>'.join(escape(part) for part in wrap(value, 26)) for value in values]
                    trace.hovertemplate = template.replace('%{' + coordinate + '}', '%{hovertext}')
                    break
    for coordinate in ('x', 'y'):
        axis = getattr(figure.layout, coordinate + 'axis')
        if axis.visible is False or 'hour' not in (axis.title.text or '').casefold():
            continue
        values = [finite_number(value) for trace in figure.data
                  for value in (getattr(trace, coordinate, None) if getattr(trace, coordinate, None) is not None else [])]
        maximum = max((value for value in values if value is not None), default=1.)
        lower, upper = axis.range if axis.range else (0, max(1., maximum * 1.1))
        tickvals, ticktext = duration_ticks(lower, upper)
        axis.update(tickmode='array', tickvals=tickvals, ticktext=ticktext, title='Duration (HH:MM)')
        figure.update_layout(meta={**(figure.layout.meta or {}), 'duration_axis_orientation': coordinate})
    return figure


def safe_chart(function=None, *, height=CHART_HEIGHT):
    """A malformed visualization never takes down its siblings."""
    def decorate(builder):
        params = signature(builder)
        @wraps(builder)
        def guarded(*args, **kwargs):
            bound = params.bind(*args, **kwargs)
            bound.apply_defaults()
            dark = bound.arguments.get('is_dark', True)
            try:
                for value in bound.arguments.values():
                    if isinstance(value, pd.DataFrame) and value.attrs.get('chart_error'):
                        return state_figure(value.attrs['chart_error'], dark, height)
                figure = builder(*args, **kwargs)
                if isinstance(figure, tuple):
                    return (finish_chart(figure[0], dark), *figure[1:])
                return finish_chart(figure, dark)
            except Exception:
                log.exception('Chart rendering failed: %s', builder.__name__)
                figure = state_figure('Chart data unavailable. Refresh to retry.', dark, height)
                return (figure, 0) if builder.__name__ == 'build_activity_calendar' else figure
        return guarded
    return decorate(function) if function else decorate

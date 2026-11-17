"""Main dashboard KPI overview, also used by the standalone preview.

All values are sourced from the existing kpis/funnel_map contracts. The panels
visualize duration shares. The unassigned pool also reports its task count.
"""
from __future__ import annotations

import math
from dash import html

from slicing_dashboard.plots.theme import format_seconds
from slicing_dashboard.reporting.kpi_overview import ordered_kpis
from slicing_dashboard.reporting.rework_tiers import TIERS


def _number(value, default=0.0):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _duration(value):
    value = _number(value, None)
    if value is None:
        return '—'
    return format_seconds(value)


def _percent(value):
    value = _number(value, None)
    return None if value is None else f'{value:+.1f}% vs previous'


def _comparison(value, favorable_when_positive=True):
    if value is None:
        return 'neutral'
    n = _number(value)
    if n == 0:
        return 'neutral'
    return 'positive' if ((n > 0) == favorable_when_positive) else 'negative'


def _metric(label, value, secondary=None, trend=None, sentiment='neutral', extra_class=''):
    children = [
        html.Div(label, className='kpiu-label'),
        html.Div('—' if value is None else str(value), className='kpiu-number'),
    ]
    if secondary is not None:
        children.append(html.Div(secondary, className='kpiu-meta'))
    if trend is not None:
        children.append(html.Div(trend, className=f'kpiu-trend kpiu-{sentiment}'))
    return html.Div(children, className=f'kpiu-metric {extra_class}'.strip())


def _parts(items, description, format_value=_duration):
    """Segment widths reflect provided durations; no synthetic data is used."""
    known = all(_number(value, None) is not None and _number(value) >= 0 for _, value, _ in items)
    values = [max(0.0, _number(value)) for _, value, _ in items]
    denominator = sum(values)
    track = []
    if known and denominator:
        for ((label, value, color), weight) in zip(items, values):
            if weight:
                track.append(html.Div(
                    title=f'{label}: {format_value(value)}',
                    className='kpiu-segment',
                    style={'flexGrow': weight / denominator, 'backgroundColor': color},
                    role='progressbar',
                    **{'aria-label': label, 'aria-valuemin': 0, 'aria-valuemax': 100,
                       'aria-valuenow': round(100 * weight / denominator, 2),
                       'aria-valuetext': f'{format_value(value)} · {100 * weight / denominator:.1f}% of duration'},
                ))
    else:
        track.append(html.Div('No duration in stages' if known else 'Breakdown unavailable',
                              className='kpiu-empty'))
    legend = [html.Div([
        html.Span(className='kpiu-dot', style={'backgroundColor': color}),
        html.Span(label, className='kpiu-legend-name'),
        html.Strong(format_value(value), className='kpiu-legend-value'),
    ], className='kpiu-legend-item') for label, value, color in items]
    return html.Div([
        html.Div(track, className='kpiu-track', role='group', **{'aria-label': description}),
        html.Div(legend, className='kpiu-legend'),
    ], className='kpiu-distribution')


def _hours(value):
    value = _number(value, None)
    return '—' if value is None else format_seconds(value * 3600)


def build_rework_hours_metric(hours=None, status=None, is_dark=True):
    """Render duration shares from the existing, scoped rework capture."""
    colors = [f'var(--kpiu-series-{index})' for index in range(1, 5)]
    labels = ('No Rework', '1 Rework', '2 Reworks', '3+ Reworks')
    returned = [_number((hours or {}).get(tier), None) for tier in TIERS[1:]]
    returned_total = sum(returned) if all(value is not None for value in returned) else None
    return [
        html.Div([
            html.Span('Batch duration by return tier', className='kpiu-label'),
            html.Strong('Returned batches: ' + _hours(returned_total), className='kpiu-row-value'),
        ], className='kpiu-row-heading'),
        _parts([(label, (hours or {}).get(tier), color)
                for label, tier, color in zip(labels, TIERS, colors)],
               'Original batch duration by recorded return count', format_value=_hours),
        html.Div('Original video duration counted once per batch; not additional hours spent reworking · HH:MM:SS', className='kpiu-meta'),
        html.Div(status, className='kpiu-meta') if status else None,
    ]


def build_kpi_layout(kpis: dict, funnel_map: dict, is_dark: bool) -> list:
    """Render the full-width dashboard overview using the shared KPI contract."""
    kpis = ordered_kpis(kpis or {}, funnel_map or {})
    approved = _number(kpis.get('total_approved_duration'), None)
    assigned_total = _number(kpis.get('assigned_now_duration'), None)
    assigned = _number(kpis.get('assigned_duration'), None)
    rework_now = _number(kpis.get('rework_assigned_duration'), None)
    pending = _number(kpis.get('total_pending_duration'), None)
    leader = _number(kpis.get('leader_review_duration'), None)
    auditor = _number(kpis.get('auditor_review_duration'), None)
    admin = _number(kpis.get('admin_review_duration'), None)
    count = kpis.get('assignable_count')
    unavailable = bool(kpis.get('assignable_error')) or kpis.get('assignable_duration') is None

    # The pending total is authoritative. Its breakdown may be incomplete or
    # have distinct counting semantics; never invent a balancing stage.
    pending_sum = (leader + auditor + admin
                   if all(value is not None for value in (leader, auditor, admin)) else None)
    pending_note = (
        'Review stage durations differ from the period total.'
        if pending_sum is not None and pending is not None and abs(pending_sum - pending) > 1
        else None
    )

    panel = html.Section([
        html.Div([
            html.H2('Operations overview', className='kpiu-eyebrow'),
            html.Span('Durations in HH:MM:SS', className='kpiu-topnote'),
        ], className='kpiu-header'),
        html.Div([
            html.Div([
                _metric('Total Approved', _duration(approved),
                        trend=_percent(kpis.get('approved_pct')),
                        sentiment=_comparison(kpis.get('approved_pct')), extra_class='kpiu-primary'),
            ], className='kpiu-hero'),
            html.Div([
                html.Div([html.Span('Assigned Now', className='kpiu-label'),
                          html.Strong(_duration(assigned_total), className='kpiu-row-value')],
                         className='kpiu-row-heading'),
                _parts([('Assigned', assigned, 'var(--kpiu-series-1)'),
                        ('Rework in active load', rework_now, 'var(--kpiu-series-2)')], 'Assigned Now duration breakdown'),
            ], className='kpiu-workload-row kpiu-assigned'),
            html.Div([
                html.Div([html.Span('Review Total', className='kpiu-label'),
                          html.Strong(_duration(pending), className='kpiu-row-value')],
                         className='kpiu-row-heading'),
                _parts([('Leader', leader, 'var(--kpiu-series-1)'),
                        ('Auditor', auditor, 'var(--kpiu-series-2)'),
                        ('Admin', admin, 'var(--kpiu-series-3)')], 'Review Total stage duration breakdown'),
                html.Div(pending_note, className='kpiu-warning') if pending_note else None,
            ], className='kpiu-workload-row kpiu-review'),
        ], className='kpiu-main'),
        html.Div(build_rework_hours_metric(kpis.get('rework_tier_hours'), is_dark=is_dark),
                 id='kpi-rework-breakdown', className='kpiu-rework'),
        html.Div([
            _metric('Unassigned videos', 'Unavailable' if unavailable else _duration(kpis.get('assignable_duration')),
                    secondary='Pool unavailable · Refresh to retry' if unavailable else
                              f'Currently assignable · {count if count is not None else "—"} tasks'),
            _metric('Rework submitted', _duration(kpis.get('rework_duration')),
                    trend=_percent(kpis.get('rework_pct')),
                    sentiment=_comparison(kpis.get('rework_pct'), favorable_when_positive=False)),
            _metric('Error duration', _duration(kpis.get('total_error_duration')),
                    trend=_percent(kpis.get('error_pct')),
                    sentiment=_comparison(kpis.get('error_pct'), favorable_when_positive=False)),
        ], className='kpiu-metrics'),
    ], className=f'kpiu-overview {"kpiu-dark theme-dark" if is_dark else "kpiu-light theme-light"}')
    return [panel]


"""Main dashboard KPI overview, also used by the standalone preview.

All values are sourced from the existing kpis/funnel_map contracts. The panels
visualize duration shares. The unassigned pool also reports its task count.
"""
from __future__ import annotations

import math
from dash import html

from slicing_dashboard.plots.theme import format_seconds
from slicing_dashboard.reporting.kpi_overview import ordered_kpis
from slicing_dashboard.reporting.rework_tiers import TIERS, DISPLAY_TIERS


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


def _metric(label, value, secondary=None, trend=None, sentiment='neutral', extra_class='', value_id=None, trend_id=None):
    children = [
        html.Div(label, className='kpiu-label'),
        html.Div('—' if value is None else str(value), className='kpiu-number', **({'id': value_id} if value_id else {})),
    ]
    if secondary is not None:
        children.append(html.Div(secondary, className='kpiu-meta'))
    if trend is not None or trend_id:
        children.append(html.Div(trend, className=f'kpiu-trend kpiu-{sentiment}', **({'id': trend_id} if trend_id else {})))
    return html.Div(children, className=f'kpiu-metric {extra_class}'.strip())


def _parts(items, description, format_value=_duration, share_unit='duration'):
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
                       'aria-valuetext': f'{format_value(value)} · {100 * weight / denominator:.1f}% of {share_unit}'},
                ))
    else:
        track.append(html.Div(('No batches' if share_unit == 'batches' else 'No duration in stages')
                              if known else 'Breakdown unavailable',
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


def build_rework_count_metric(counts=None, status=None, is_dark=True,
                              completed_seconds=None, show_completed_hours=False):
    """Return-tier counts plus independently verified completed video hours.

    The completed-hour number is NOT distributed into the batch tier bars.
    """
    colors = [f'var(--kpiu-series-{index})' for index in range(1, 5)] + ['#8b929a']
    totals = {tier: None if counts is None else counts.get(tier)
              for tier in DISPLAY_TIERS}
    returned = [totals[tier] for tier in TIERS[1:]]
    returned_total = (sum(returned)
                      if all(isinstance(value, int) and value >= 0 for value in returned)
                      else None)
    completed = (
        [html.Div([
            html.Span('Completed video hours', className='kpiu-label'),
            html.Strong(
                format_seconds(completed_seconds) if completed_seconds is not None
                else 'Unavailable', className='kpiu-row-value'),
        ], className='kpiu-row-heading')]
        if show_completed_hours else []
    )
    return [
        *completed,
        html.Div([
            html.Span('Rework batches', className='kpiu-label'),
            html.Strong('Returned: ' + ('—' if returned_total is None
                                       else f'{returned_total:,}'),
                        className='kpiu-row-value'),
        ], className='kpiu-row-heading'),
        _parts([(tier, totals[tier], color)
                for tier, color in zip(DISPLAY_TIERS, colors)],
               'Batches by observed return tier',
               format_value=lambda value: '—' if value is None else f'{int(value):,}',
               share_unit='batches'),
        html.Div(status, className='kpiu-warning') if status else None,
    ]



def build_rework_duration_metric(hours=None, status=None, is_dark=True):
    """Exactly the heatmap's video-hour tiers, without batch-count weighting.

    'Returned' sums durations in batches with one or more recorded lifetime
    returns. It is NOT an estimate of hours spent performing rework.
    """
    colors = [f'var(--kpiu-series-{index})' for index in range(1, 5)] + ['#8b929a']
    by_tier = {tier: None if hours is None else hours.get(tier)
               for tier in DISPLAY_TIERS}
    known = [by_tier[tier] for tier in TIERS[1:]]
    returned = (sum(known) if all(_number(x, None) is not None and _number(x) >= 0
                                  for x in known) else None)
    return [
        html.Div([
            html.Span('Video hours · returned batches', className='kpiu-label'),
            html.Strong(_hours(returned), className='kpiu-row-value'),
        ], className='kpiu-row-heading'),
        _parts([(tier, by_tier[tier], color)
                for tier, color in zip(DISPLAY_TIERS, colors)],
               'Video duration classified by observed lifetime batch returns',
               format_value=_hours, share_unit='video duration'),
        html.Div(status, className='kpiu-warning') if status else None,
    ]


def build_secondary_metrics(kpis):
    count = kpis.get('assignable_count')
    unavailable = bool(kpis.get('assignable_error')) or kpis.get('assignable_duration') is None
    return [
        _metric('Unassigned videos · current pool', 'Unavailable' if unavailable else _duration(kpis.get('assignable_duration')),
                secondary='Pool unavailable' if unavailable else f'Currently assignable · {count if count is not None else "—"} tasks'),
        _metric('Rework submitted · period', _duration(kpis.get('rework_duration')),
                trend=_percent(kpis.get('rework_pct')),
                sentiment=_comparison(kpis.get('rework_pct'), favorable_when_positive=False)),
        _metric('Error duration · period', _duration(kpis.get('total_error_duration')),
                trend=_percent(kpis.get('error_pct')),
                sentiment=_comparison(kpis.get('error_pct'), favorable_when_positive=False)),
    ]


def build_workload_metric(kpis, kind, note=None):
    if kind == 'assigned':
        label, total = 'Assigned Now · current queue', kpis.get('assigned_now_duration')
        parts = [('Assigned', kpis.get('assigned_duration'), 'var(--kpiu-series-1)'),
                 ('Rework in active load', kpis.get('rework_assigned_duration'), 'var(--kpiu-series-2)')]
    else:
        label, total = 'Review Total · current queue', kpis.get('total_pending_duration')
        parts = [(stage, kpis.get(stage.lower() + '_review_duration'), f'var(--kpiu-series-{index})')
                 for index, stage in enumerate(('Leader', 'Auditor', 'Admin'), 1)]
    return [html.Div([html.Span(label, className='kpiu-label'), html.Strong(_duration(total), className='kpiu-row-value')],
                     className='kpiu-row-heading'),
            _parts(parts, label + ' duration breakdown'),
            html.Div(note, className='kpiu-warning') if note else None]


def build_kpi_layout(kpis: dict, funnel_map: dict, is_dark: bool) -> list:
    """Render the full-width dashboard overview using the shared KPI contract."""
    kpis = ordered_kpis(kpis or {}, funnel_map or {})
    approved = _number(kpis.get('total_approved_duration'), None)
    pending = _number(kpis.get('total_pending_duration'), None)
    leader = _number(kpis.get('leader_review_duration'), None)
    auditor = _number(kpis.get('auditor_review_duration'), None)
    admin = _number(kpis.get('admin_review_duration'), None)

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
        html.Div([html.H2('Operations overview', className='kpiu-eyebrow')], className='kpiu-header'),
        html.Div([
            html.Div([
                _metric('Total Approved · period task completion', _duration(approved),
                        trend=_percent(kpis.get('approved_pct')),
                        sentiment=_comparison(kpis.get('approved_pct')), extra_class='kpiu-primary',
                        value_id='kpi-approved-value', trend_id='kpi-approved-comparison'),
            ], className='kpiu-hero'),
            html.Div(build_workload_metric(kpis, 'assigned'), id='kpi-assigned', className='kpiu-workload-row kpiu-assigned'),
            html.Div(build_workload_metric(kpis, 'pending', pending_note), id='kpi-review', className='kpiu-workload-row kpiu-review'),
        ], className='kpiu-main'),
        html.Div(build_rework_count_metric(is_dark=is_dark),
                 id='kpi-rework-breakdown', className='kpiu-rework'),
        html.Div(build_secondary_metrics(kpis), id='kpi-secondary', className='kpiu-metrics'),
    ], id='kpi-overview', className=f'kpiu-overview {"kpiu-dark theme-dark" if is_dark else "kpiu-light theme-light"}')
    return [panel]


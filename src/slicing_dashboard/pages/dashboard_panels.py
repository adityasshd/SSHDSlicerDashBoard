"""Saved first paint and independent updates for the dashboard's five panels."""
from uuid import uuid4

import dash
from dash import Input, Output, State, dcc, html
import dash_bootstrap_components as dbc

from slicing_dashboard.reporting.dashboard_panels import (
    KINDS, capture_panel, saved_panel, latest_saved_panel, panel_frame, selected_summary,
)
from slicing_dashboard.plots import (
    build_kpi_layout, build_individual_chart, build_rework_ratio_chart,
    build_assigned_chart, build_pending_chart,
)
from slicing_dashboard.plots.guardrails import state_figure
from slicing_dashboard.runtime import viewer_mode
from slicing_dashboard.reporting.settlement_snapshots import manager_snapshot, period_for_range

GRAPH_IDS = {'completion': 'individual-chart', 'rework': 'rework-ratio-chart',
             'assigned': 'assigned-chart', 'pending': 'pending-chart'}


def panel_stores():
    return [dcc.Store(id='dashboard-panel-request'),
            dcc.Store(id='dashboard-pending-request'),
            *[dcc.Store(id=f'dashboard-{phase}-{kind}')
              for kind in KINDS for phase in ('saved', 'live', 'ready', 'painted')]]


def matching_packet(request, packet):
    return packet if packet and packet.get('request_id') == request.get('id') else None


def choose_packet(request, saved, live):
    saved, live = matching_packet(request, saved), matching_packet(request, live)
    if request.get('frozen'):
        if saved and saved.get('available'):
            return saved, 'Final settled-period snapshot · read only'
        return None, 'No verified snapshot exists for this settled period. Raw history has not been archived.'
    if live and live.get('available'):
        return live, f"Captured {live['captured_at']}"
    if saved and saved.get('available'):
        if viewer_mode():
            fallback = saved.get('fallback')
            if fallback:
                return saved, (
                    f"STALE · Saved through {fallback['as_of_date']} "
                    f"(requested through {fallback['requested_end']}); "
                    f"captured {saved['captured_at']}. Not current.")
            return saved, 'Saved data'
        state = 'Latest check failed' if live else 'Checking latest data'
        return saved, f"Saved {saved['captured_at']} · {state}"
    if viewer_mode():
        return None, 'No saved data for this range. Waiting for updated data.'
    return None, 'Latest data unavailable. Refresh to retry.' if live else 'Loading latest data…'


def render_panel(kind, request, saved, live, selected, theme, roster, show_counts=False,
                 completion_state='All', completed_evidence=None):
    dark = (theme or 0) % 2 == 0
    packet, status = choose_packet(request, saved, live)
    if not packet:
        # Even if the batch cohort failed, an independently verified task
        # completion report can still show its full hour total. Do not let the
        # missing batch record hide valid paid video hours.
        if kind == 'rework' and completion_state == 'Completed':
            from slicing_dashboard.plots.completed_hours_heatmap import (
                build_completed_hours_heatmap, completion_total)
            if completion_total(completed_evidence, selected) is not None:
                return build_completed_hours_heatmap(completed_evidence, dark, selected, compact=True), status
        content = (dbc.Alert(status, color='secondary') if kind == 'summary'
                   else state_figure(status, dark))
        return content, status
    if kind == 'summary':
        fallback = packet.get('fallback')
        label = (f"STALE · Through {fallback['as_of_date']} · Not live"
                 if fallback else 'Updated' if live and live.get('available') else 'Saved capture')
        return build_kpi_layout(selected_summary(packet['data'], selected, roster),
                                packet['data']['funnel'], dark), html.Span(
                                    label, className='text-warning' if fallback else '', title=status)
    frame = panel_frame(packet)
    if selected is not None and 'User' in frame:
        frame = frame[frame['User'].isin(selected)]
    if kind == 'completion':
        figure = build_individual_chart(frame, request['start'], request['end'], dark)
    elif kind == 'rework':
        figure = build_rework_ratio_chart(
            frame, request['start'], dark, None, False,
            show_counts=show_counts, completion_state=completion_state,
            completed_evidence=completed_evidence, selected_users=selected)
    elif kind == 'assigned':
        figure = build_assigned_chart(frame, dark, show_counts=show_counts)
    else:
        figure = build_pending_chart(frame, dark, show_counts=show_counts)
    return figure, status


def render_rework_hours(request, saved, live, selected, theme, completion_state='All',
                        completed_evidence=None):
    """Backwards-compatible callback name; render batch COUNTS, not hours."""
    from slicing_dashboard.plots.kpi_overview import build_rework_count_metric
    from slicing_dashboard.reporting.rework_tiers import rework_counts
    from slicing_dashboard.plots.completed_hours_heatmap import completion_total

    dark = (theme or 0) % 2 == 0
    show_completion = completion_state == 'Completed'
    verified_seconds = (completion_total(completed_evidence, selected)
                        if show_completion else None)
    packet, status = choose_packet(request, saved, live)
    if not packet:
        return build_rework_count_metric(
            status=status, is_dark=dark,
            completed_seconds=verified_seconds, show_completed_hours=show_completion)
    try:
        frame = panel_frame(packet)
        if selected is not None and 'User' in frame:
            frame = frame[frame['User'].isin(selected)]
        if completion_state in ('Completed', 'Pending approvals'):
            if 'Completion State' not in frame:
                raise ValueError('Latest batch status unavailable')
            frame = frame[frame['Completion State'] == completion_state]
        counts = rework_counts(frame)
    except (KeyError, TypeError, ValueError):
        return build_rework_count_metric(
            status='Batch counts unavailable.', is_dark=dark,
            completed_seconds=verified_seconds, show_completed_hours=show_completion)
    # Stale and read-error states are necessary to avoid presenting old data
    # as fresh. Avoid verbose calculation notes for valid captures.
    return build_rework_count_metric(
        counts, status=visible_status(request, saved, live), is_dark=dark,
        completed_seconds=verified_seconds, show_completed_hours=show_completion)


def visible_status(request, saved, live):
    """Keep missing/stale evidence visible without capture metadata in the UI."""
    packet, status = choose_packet(request, saved, live)
    if not packet:
        return status
    if packet.get('fallback'):
        return 'Saved data is stale; waiting for updated data.'
    if live and matching_packet(request, live) and not live.get('available'):
        return 'Latest read failed; showing saved data.'
    return ''


def period_completion(request, saved, live):
    """Exact period task output; no lifetime batch durations or inferred dates."""
    if not request:
        return {'available': False, 'rows': []}
    packet, _ = choose_packet(request, saved, live)
    if not packet:
        return {'available': False, 'rows': []}
    frame = panel_frame(packet)
    fallback = packet.get('fallback') or {}
    return {'available': True, 'start': request['start'],
            'end': fallback.get('period_end', request['end']),
            'requested_end': request['end'],
            'is_snapshot': bool(fallback),
            'rows': [{'User': row['User'], 'seconds': row['Completed Duration'],
                      'tasks': row.get('Completed Tasks')} for row in frame.to_dict('records')]}


def overview_values(kind, request, saved, live, selected, theme, completion_state='All',
                    completed_evidence=None):
    """Derive an overview section from the exact packet used by its chart.

    Sections stay mounted, so an independent summary repaint cannot erase
    another panel's data. No source reads or synthetic balancing values.
    """
    from slicing_dashboard.plots.kpi_overview import build_workload_metric
    from slicing_dashboard.plots.theme import format_seconds
    from slicing_dashboard.plots.guardrails import checked_frame
    packet, _ = choose_packet(request, saved, live)
    if kind == 'rework':
        return render_rework_hours(request, saved, live, selected, theme,
                                   completion_state, completed_evidence)
    if not packet:
        return '—' if kind == 'completion' else build_workload_metric({}, kind, visible_status(request, saved, live))
    try:
        frame = panel_frame(packet)
        if selected is not None and 'User' in frame:
            frame = frame[frame['User'].isin(selected)]
        if kind == 'completion':
            frame = checked_frame(frame, ['User', 'Completed Duration'], ['Completed Duration'])
            return format_seconds(frame['Completed Duration'].sum())
        frame = checked_frame(frame, ['Stage', 'Duration'], ['Duration'])
        durations = frame.groupby('Stage')['Duration'].sum()
        if kind == 'pending':
            kpis = {stage.lower() + '_review_duration': float(durations.get('Pending ' + stage, 0))
                    for stage in ('Leader', 'Auditor', 'Admin')}
            kpis['total_pending_duration'] = sum(kpis.values())
        else:
            kpis = {'assigned_duration': float(durations.get('New Assigned', 0)),
                    'rework_assigned_duration': float(durations.get('Rework Assigned', 0))}
            kpis['assigned_now_duration'] = sum(kpis.values())
        return build_workload_metric(kpis, kind, visible_status(request, saved, live))
    except (KeyError, TypeError, ValueError):
        return '—' if kind == 'completion' else build_workload_metric({}, kind, 'Workload unavailable.')


def register_dashboard_panels(app, manager, roster):
    @app.callback(Output('kpi-overview', 'className'), Input('theme-toggle', 'n_clicks'))
    def overview_theme(theme):
        return 'kpiu-overview ' + ('kpiu-dark theme-dark' if (theme or 0) % 2 == 0 else 'kpiu-light theme-light')

    @app.callback(
        Output('dashboard-panel-request', 'data'),
        Output('dashboard-pending-request', 'data'),
        *[Output(f'dashboard-saved-{kind}', 'data') for kind in KINDS],
        Input('date-from', 'value'), Input('date-to', 'value'),
        Input('refresh-btn', 'n_clicks'), Input('auto-refresh-interval', 'n_intervals'),
        Input('report-location', 'pathname'),
        Input('workflow-notification-interval', 'n_intervals'), Input('workflow-bell', 'n_clicks'),
    )
    def request_panels(start, end, clicks, intervals, pathname, notifications, bell):
        if pathname not in (None, '/', '/dashboard') or not start or not end:
            raise dash.exceptions.PreventUpdate
        trigger = dash.ctx.triggered_id
        request = {'id': uuid4().hex, 'start': start, 'end': end,
                   'force': trigger in ('refresh-btn', 'auto-refresh-interval'),
                   'pending_force': trigger in ('workflow-notification-interval', 'workflow-bell')}
        closed = period_for_range(manager.get_available_periods(), start, end)
        if closed is not None:
            # Never read live queues or rolling panel keys for a settled period.
            request['frozen'] = True
            try:
                snapshot = manager_snapshot(manager, start, end)
            except (ValueError, KeyError, TypeError):
                snapshot = None
            packets = (snapshot or {}).get('panels', {})
            frozen_saved = [
                {**packets.get(kind, {'available': False}), 'request_id': request['id']}
                for kind in KINDS
            ]
            return request, request, *frozen_saved
        # A manual refresh in viewer mode reloads MongoDB's persisted snapshot.
        # Warm Vercel instances otherwise keep a stale import-time copy forever.
        if viewer_mode() and trigger == 'refresh-btn':
            manager._load_snapshot()
        # Notification checks affect the current review queue only. A new shared
        # request ID would otherwise restart all five panel capture pipelines.
        if request['pending_force']:
            packet = (saved_panel(manager, 'pending', start, end)
                      or (latest_saved_panel(manager, 'pending', start, end)
                          if viewer_mode() else None)
                      or {'available': False})
            return (dash.no_update, request,
                    *[{**packet, 'request_id': request['id']} if kind == 'pending'
                      else dash.no_update for kind in KINDS])
        saved = []
        for kind in KINDS:
            packet = (saved_panel(manager, kind, start, end)
                      or (latest_saved_panel(manager, kind, start, end)
                          if viewer_mode() else None)
                      or {'available': False})
            saved.append({**packet, 'request_id': request['id']})
        return request, request, *saved

    for kind in KINDS:
        _register_panel(app, manager, roster, kind)

def _register_panel(app, manager, roster, kind):
    request_store = 'dashboard-pending-request' if kind == 'pending' else 'dashboard-panel-request'
    outputs = ([Output('kpi-secondary', 'children'), Output('refresh-status', 'children'),
                Output('kpi-approved-comparison', 'children'), Output('kpi-approved-comparison', 'className')]
               if kind == 'summary' else
               [Output(GRAPH_IDS[kind], 'figure'), Output(GRAPH_IDS[kind] + '-status', 'children'),
                Output({'completion': 'kpi-approved-value', 'rework': 'kpi-rework-breakdown',
                        'assigned': 'kpi-assigned', 'pending': 'kpi-review'}[kind], 'children')])
    if kind == 'pending':
        outputs.append(Output('review-workload-chart', 'figure'))
    rework_input = [Input('rework-completion-state', 'value')] if kind == 'rework' else []
    rework_state = [State('rework-completion-state', 'value')] if kind == 'rework' else []
    # Saved completion comes from the same exact range/keyed source, but must
    # repaint independently after its capture finishes.
    completion_input = ([Input('dashboard-saved-completion', 'data'),
                         Input('dashboard-live-completion', 'data')]
                        if kind == 'rework' else [])
    completion_state_stores = ([State('dashboard-saved-completion', 'data'),
                                State('dashboard-live-completion', 'data')]
                               if kind == 'rework' else [])
    def render(request, saved, live, selected, theme, completion_state='Completed',
               saved_completion=None, live_completion=None):
        if kind == 'summary':
            from slicing_dashboard.plots.kpi_overview import build_secondary_metrics, _percent, _comparison
            packet, status = choose_packet(request, saved, live)
            kpis = selected_summary(packet['data'], selected, roster) if packet else {}
            current = matching_packet(request, live)
            label = ('Settled period · read only' if request.get('frozen') else
                     'Updated' if current and current.get('available') else 'Saved data')
            return (build_secondary_metrics(kpis), visible_status(request, saved, live) or label,
                    _percent(kpis.get('approved_pct')), 'kpiu-trend kpiu-' + _comparison(kpis.get('approved_pct')))
        if kind == 'rework' and completion_state == 'Verified completed hours':
            from slicing_dashboard.plots.completed_hours_heatmap import (
                build_completed_hours_heatmap, completion_total)
            from slicing_dashboard.plots.theme import format_seconds
            evidence = period_completion(request, saved_completion, live_completion)
            dark = (theme or 0) % 2 == 0
            figure = build_completed_hours_heatmap(evidence, dark, selected)
            seconds = completion_total(evidence, selected)
            label = format_seconds(seconds) if seconds is not None else 'Unavailable'
            caution = ('Source-date completed video output; return-tier hours are not attributed.'
                       if seconds is not None else
                       'Exact-range completed-hour evidence missing. No batch durations substituted.')
            if evidence.get('is_snapshot'):
                caution += f" Saved only through {evidence['end']}; not the requested end."
            overview = html.Div([
                html.Span('Verified Completed Hours', className='kpiu-label'),
                html.Strong(label, className='kpiu-value'),
                html.Div(caution, className='kpiu-meta'),
            ])
            return figure, visible_status(request, saved_completion, live_completion), overview
        # Rework tiers are batch counts; independently verified completed
        # task-video hours get their own column, never allocated across tiers.
        evidence = (period_completion(request, saved_completion, live_completion)
                    if kind == 'rework' and completion_state == 'Completed'
                    else None)
        figure, _ = render_panel(kind, request, saved, live, selected, theme, roster,
                                 completion_state=completion_state,
                                 completed_evidence=evidence)
        result = (figure, visible_status(request, saved, live),
                  overview_values(kind, request, saved, live, selected, theme,
                                  completion_state, completed_evidence=evidence))
        if kind == 'pending':
            from slicing_dashboard.plots.overview_charts import build_review_workload_donut
            packet, status = choose_packet(request, saved, live)
            dark = (theme or 0) % 2 == 0
            if packet:
                frame = panel_frame(packet)
                if selected is not None and 'User' in frame:
                    frame = frame[frame['User'].isin(selected)]
                donut = build_review_workload_donut(frame, dark)
            else:
                donut = state_figure(status, dark, 340)
            return *result, donut
        return result

    @app.callback(Output(f'dashboard-live-{kind}', 'data'),
                  Input(f'dashboard-ready-{kind}', 'data'), State(request_store, 'data'))
    def capture(ready, request):
        if viewer_mode() or (request or {}).get('frozen'):
            raise dash.exceptions.PreventUpdate
        if not request or not matching_packet(request, ready):
            raise dash.exceptions.PreventUpdate
        packet = capture_panel(manager, kind, request['start'], request['end'],
                               force=request['force'] or (kind == 'pending' and request['pending_force']))
        return {**packet, 'request_id': request['id']}

    # No live-store Input here: Dash would wait for that store's source callback
    # before painting the saved result.
    @app.callback(*outputs, Output(f'dashboard-ready-{kind}', 'data'),
                  Output(f'dashboard-painted-{kind}', 'data'),
                  Input(request_store, 'data'), Input(f'dashboard-saved-{kind}', 'data'),
                  Input('selected-users-store', 'data'), Input('theme-toggle', 'n_clicks'),
                  *rework_input, *completion_input,
                  State(f'dashboard-live-{kind}', 'data'), State('report-location', 'pathname'),
                  State(f'dashboard-ready-{kind}', 'data'))
    def paint_saved(request, saved, selected, theme, *arguments):
        completion_state, arguments = ((arguments[0] or 'Completed'), arguments[1:]) if kind == 'rework' else ('All', arguments)
        saved_completion, live_completion = (arguments[:2] if kind == 'rework' else (None, None))
        if kind == 'rework':
            arguments = arguments[2:]
        live, pathname, ready = arguments
        if not request or pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        # Start this panel's live read only after its saved/loading response.
        # Otherwise a fast live response can be overwritten by a slower first
        # paint from a different callback, leaving the selected range stale.
        start_capture = (dash.no_update if viewer_mode() or request.get('frozen') or matching_packet(request, ready)
                         else {'request_id': request['id']})
        painted = {'request_id': request['id'], 'id': uuid4().hex}
        return *render(request, saved, live, selected, theme, completion_state,
                       saved_completion, live_completion), start_capture, painted

    @app.callback(*[Output(output.component_id, output.component_property, allow_duplicate=True)
                    for output in outputs],
                  Input(f'dashboard-live-{kind}', 'data'),
                  Input(f'dashboard-painted-{kind}', 'data'),
                  State(request_store, 'data'), State(f'dashboard-saved-{kind}', 'data'),
                  State('selected-users-store', 'data'), State('theme-toggle', 'n_clicks'),
                  State('report-location', 'pathname'), *rework_state,
                  *completion_state_stores, prevent_initial_call=True)
    def paint_live(live, painted, request, saved, selected, theme, pathname,
                   completion_state='All', saved_completion=None, live_completion=None):
        if not request or request.get('frozen') or not matching_packet(request, live) or pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        return render(request, saved, live, selected, theme, completion_state or 'Completed',
                      saved_completion, live_completion)

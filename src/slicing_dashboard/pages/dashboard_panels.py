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
            return saved, f"Saved {saved['captured_at']}"
        state = 'Latest check failed' if live else 'Checking latest data'
        return saved, f"Saved {saved['captured_at']} · {state}"
    if viewer_mode():
        return None, 'No saved capture for this range. Waiting for the data collector.'
    return None, 'Latest data unavailable. Refresh to retry.' if live else 'Loading latest data…'


def render_panel(kind, request, saved, live, selected, theme, roster, show_counts=False, completion_state='All'):
    dark = (theme or 0) % 2 == 0
    packet, status = choose_packet(request, saved, live)
    if not packet:
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
        figure = build_rework_ratio_chart(frame, request['start'], dark, None, False, show_counts=show_counts, completion_state=completion_state)
    elif kind == 'assigned':
        figure = build_assigned_chart(frame, dark, show_counts=show_counts)
    else:
        figure = build_pending_chart(frame, dark, show_counts=show_counts)
    return figure, status


def render_rework_hours(request, saved, live, selected, theme):
    """Reuse rework packets so the new KPI never starts another source read."""
    from slicing_dashboard.plots.kpi_overview import build_rework_hours_metric
    from slicing_dashboard.reporting.rework_tiers import rework_hours

    dark = (theme or 0) % 2 == 0
    packet, status = choose_packet(request, saved, live)
    if not packet:
        return build_rework_hours_metric(status=status, is_dark=dark)
    try:
        frame = panel_frame(packet)
        if selected is not None and 'User' in frame:
            frame = frame[frame['User'].isin(selected)]
        hours = rework_hours(frame)
    except (KeyError, TypeError, ValueError):
        return build_rework_hours_metric(status='Rework hours unavailable. Refresh to retry.', is_dark=dark)
    note = ('Some tier hours are unavailable in this capture.' if any(value is None for value in hours.values())
            else '')
    current_live = matching_packet(request, live)
    if not current_live or not current_live.get('available'):
        note += f' {status}'
    return build_rework_hours_metric(hours, status=note, is_dark=dark)


def register_dashboard_panels(app, manager, roster):
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

    @app.callback(Output('kpi-rework-breakdown', 'children'),
                  Input('kpi-cards', 'children'), Input('dashboard-panel-request', 'data'),
                  Input('dashboard-saved-rework', 'data'), Input('dashboard-live-rework', 'data'),
                  Input('selected-users-store', 'data'), Input('theme-toggle', 'n_clicks'),
                  State('report-location', 'pathname'))
    def paint_rework_hours(layout, request, saved, live, selected, theme, pathname):
        if not request or pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        # The summary replaces its children when its data or theme changes.
        # Repaint from the same packet after that replacement, without refetching.
        panels = layout if isinstance(layout, list) else [layout]
        if not any(isinstance(panel, dict) and 'kpiu-overview' in panel.get('props', {}).get('className', '')
                   for panel in panels):
            raise dash.exceptions.PreventUpdate
        return render_rework_hours(request, saved, live, selected, theme)

    def review_mix(request, saved, live, selected, theme, pathname):
        if not request or pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        from slicing_dashboard.plots.overview_charts import build_review_workload_donut
        packet, status = choose_packet(request, saved, live)
        dark = (theme or 0) % 2 == 0
        if not packet:
            return state_figure(status, dark, 340)
        frame = panel_frame(packet)
        if selected is not None and 'User' in frame:
            frame = frame[frame['User'].isin(selected)]
        return build_review_workload_donut(frame, dark)

    @app.callback(Output('review-workload-chart', 'figure'),
                  Input('dashboard-pending-request', 'data'), Input('dashboard-saved-pending', 'data'),
                  Input('selected-users-store', 'data'), Input('theme-toggle', 'n_clicks'),
                  State('dashboard-live-pending', 'data'), State('report-location', 'pathname'))
    def paint_mix_saved(request, saved, selected, theme, live, pathname):
        return review_mix(request, saved, live, selected, theme, pathname)

    @app.callback(Output('review-workload-chart', 'figure', allow_duplicate=True),
                  Input('dashboard-live-pending', 'data'), State('dashboard-pending-request', 'data'),
                  State('dashboard-saved-pending', 'data'), State('selected-users-store', 'data'),
                  State('theme-toggle', 'n_clicks'), State('report-location', 'pathname'), prevent_initial_call=True)
    def paint_mix_live(live, request, saved, selected, theme, pathname):
        if not request or not matching_packet(request, live):
            raise dash.exceptions.PreventUpdate
        return review_mix(request, saved, live, selected, theme, pathname)


def _register_panel(app, manager, roster, kind):
    request_store = 'dashboard-pending-request' if kind == 'pending' else 'dashboard-panel-request'
    outputs = ([Output('kpi-cards', 'children'), Output('refresh-status', 'children')]
               if kind == 'summary' else
               [Output(GRAPH_IDS[kind], 'figure'), Output(GRAPH_IDS[kind] + '-status', 'children')])
    has_counts = kind in ('rework', 'pending', 'assigned')
    counts_input = [Input(GRAPH_IDS[kind] + '-counts', 'value')] if has_counts else []
    counts_state = [State(GRAPH_IDS[kind] + '-counts', 'value')] if has_counts else []
    rework_input = [Input('rework-completion-state', 'value')] if kind == 'rework' else []
    rework_state = [State('rework-completion-state', 'value')] if kind == 'rework' else []

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
                  *counts_input, *rework_input,
                  State(f'dashboard-live-{kind}', 'data'), State('report-location', 'pathname'),
                  State(f'dashboard-ready-{kind}', 'data'))
    def paint_saved(request, saved, selected, theme, *arguments):
        counts, arguments = (arguments[0], arguments[1:]) if has_counts else ([], arguments)
        completion_state, arguments = ((arguments[0] or 'All'), arguments[1:]) if kind == 'rework' else ('All', arguments)
        live, pathname, ready = arguments
        if not request or pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        # Start this panel's live read only after its saved/loading response.
        # Otherwise a fast live response can be overwritten by a slower first
        # paint from a different callback, leaving the selected range stale.
        start_capture = (dash.no_update if viewer_mode() or request.get('frozen') or matching_packet(request, ready)
                         else {'request_id': request['id']})
        painted = {'request_id': request['id'], 'id': uuid4().hex}
        return *render_panel(kind, request, saved, live, selected, theme, roster, 'counts' in (counts or []), completion_state), start_capture, painted

    @app.callback(*[Output(output.component_id, output.component_property, allow_duplicate=True)
                    for output in outputs],
                  Input(f'dashboard-live-{kind}', 'data'),
                  Input(f'dashboard-painted-{kind}', 'data'),
                  State(request_store, 'data'), State(f'dashboard-saved-{kind}', 'data'),
                  State('selected-users-store', 'data'), State('theme-toggle', 'n_clicks'),
                  State('report-location', 'pathname'), *counts_state, *rework_state, prevent_initial_call=True)
    def paint_live(live, painted, request, saved, selected, theme, pathname, counts=None, completion_state='All'):
        if not request or request.get('frozen') or not matching_packet(request, live) or pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        return render_panel(kind, request, saved, live, selected, theme, roster, 'counts' in (counts or []), completion_state or 'All')

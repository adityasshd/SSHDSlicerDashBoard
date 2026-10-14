"""Paint recorded trend data before checking mutable completion statuses."""
from datetime import date

import dash
from dash import Input, Output, State, dcc

from slicing_dashboard.reporting.dashboard_reports import date_range


def trend_stores():
    return [dcc.Store(id='dashboard-trend-ready'), dcc.Store(id='dashboard-trend-live')]


def matching_live(data, live):
    return bool(data and live and data.get('request_id')
                and live.get('request_id') == data['request_id'])


def retain_completion(data, checked):
    """A failed source or database check keeps the previously rendered evidence."""
    saved = {day['date']: day for day in data.get('efficiency_history', [])}
    latest = {day['date']: day for day in checked}
    days = (date.fromisoformat(data['range_end']) - date.fromisoformat(data['range_start'])).days + 1
    rows = []
    for day in date_range(data['range_end'], days):
        current = latest.get(day)
        if current and current.get('metadata', {}).get('available'):
            rows.append(current)
        else:
            retained = saved.get(day) or current or {'date': day, 'rows': [], 'metadata': {'available': False}}
            error = (current or {}).get('metadata', {}).get('error', 'EfficiencyReadFailed')
            rows.append({**retained, 'metadata': {**retained['metadata'], 'error': error}})
    return rows


def register_dashboard_trend(app, manager, render, roster=None):
    @app.callback(
        Output('approval-trend-chart', 'figure'), Output('approval-trend-status', 'children'),
        Output('dashboard-trend-ready', 'data'),
        Input('dashboard-trend-store', 'data'), Input('selected-users-store', 'data'),
        Input('theme-toggle', 'n_clicks'), Input('report-location', 'pathname'),
        State('dashboard-trend-live', 'data'), State('dashboard-trend-ready', 'data'),
    )
    def paint_saved(data, users, theme, pathname, live, ready):
        display = live if matching_live(data, live) else data
        figure, note = render(display, users, theme, pathname)
        request_id = (data or {}).get('request_id')
        request = dash.no_update
        if request_id and not data.get('validation_error'):
            if not matching_live(data, live):
                note += ' Checking latest completion and approval statuses…'
            if not ready or ready.get('request_id') != request_id:
                request = {'request_id': request_id, 'start': data['range_start'],
                           'end': data['range_end'], 'force': data.get('force_refresh', False)}
        return figure, note, request

    @app.callback(Output('dashboard-trend-live', 'data'),
                  Input('dashboard-trend-ready', 'data'), State('dashboard-trend-store', 'data'))
    def capture(ready, data):
        if not matching_live(data, ready):
            raise dash.exceptions.PreventUpdate
        efficiency = manager.get_efficiency_history(ready['start'], ready['end'],
                                                     force_refresh=ready['force'])
        # Read approvals again after the separate workflow poll has had time to
        # persist. Neither task nor workflow ingestion gates recorded first paint.
        approvals = manager.get_approval_data(ready['start'], ready['end'],
                                             refresh_batches=True, force_refresh=ready['force'])
        if approvals.get('error') and not approvals.get('rows') and 'funnel' not in approvals:
            approvals = {**data.get('approvals', {}), 'error': approvals['error']}
        return {**data, 'efficiency_history': retain_completion(data, efficiency), 'approvals': approvals}

    @app.callback(
        Output('approval-trend-chart', 'figure', allow_duplicate=True),
        Output('approval-trend-status', 'children', allow_duplicate=True),
        Input('dashboard-trend-live', 'data'),
        State('dashboard-trend-store', 'data'), State('selected-users-store', 'data'),
        State('theme-toggle', 'n_clicks'), State('report-location', 'pathname'),
        prevent_initial_call=True,
    )
    def paint_live(live, data, users, theme, pathname):
        if not matching_live(data, live):
            raise dash.exceptions.PreventUpdate
        return render(live, users, theme, pathname)

    @app.callback(Output('approval-outcomes-chart', 'figure'),
                  Input('dashboard-trend-store', 'data'), Input('dashboard-trend-live', 'data'),
                  Input('selected-users-store', 'data'), Input('theme-toggle', 'n_clicks'),
                  Input('report-location', 'pathname'))
    def paint_outcomes(data, live, users, theme, pathname):
        if pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        from slicing_dashboard.plots.approval_outcomes_chart import build_approval_outcomes_chart
        from slicing_dashboard.reporting.approval_funnel import prepare_funnel
        display = (live if matching_live(data, live) else data) or {}
        days = [day['date'] for day in display.get('history', [])]
        selection = users if users and (roster is None or len(users) < len(roster)) else None
        _, totals = prepare_funnel(display.get('approvals', {}).get('funnel', {}), days, selection)
        return build_approval_outcomes_chart(totals, (theme or 0) % 2 == 0,
                                            available='funnel' in display.get('approvals', {}),
                                            start=display.get('range_start'), end=display.get('range_end'))

    return paint_saved, capture, paint_live

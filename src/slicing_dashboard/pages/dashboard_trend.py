"""Paint recorded trend data before checking mutable completion statuses."""
from datetime import date, timedelta

import dash
from dash import Input, Output, State, dcc

from slicing_dashboard.reporting.dashboard_reports import date_range
from slicing_dashboard.runtime import viewer_mode


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
        if request_id and not data.get('validation_error') and not data.get('frozen') and not viewer_mode():
            if not matching_live(data, live):
                note += ' Checking latest completion and approval statuses…'
            if not ready or ready.get('request_id') != request_id:
                request = {'request_id': request_id, 'start': data['range_start'],
                           'end': data['range_end'], 'force': data.get('force_refresh', False)}
        return figure, note, request

    @app.callback(Output('dashboard-trend-live', 'data'),
                  Input('dashboard-trend-ready', 'data'), State('dashboard-trend-store', 'data'))
    def capture(ready, data):
        if viewer_mode() or (data or {}).get('frozen'):
            raise dash.exceptions.PreventUpdate
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

    def progression(data, live, users, theme, pathname):
        if pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        from slicing_dashboard.plots.overview_charts import build_approval_progression
        display = (live if matching_live(data, live) else data) or {}
        # A missing daily efficiency observation must not erase a saved batch
        # approval cohort. Derive the dates from the selected report range.
        try:
            start = date.fromisoformat(display['range_start'])
            end = date.fromisoformat(display['range_end'])
            if end < start or (end - start).days > 370:
                raise ValueError('Invalid batch cohort scope')
            dates = [(start + timedelta(days=n)).isoformat()
                     for n in range((end - start).days + 1)]
        except (KeyError, TypeError, ValueError):
            dates = []
        selection = users if users is not None and (roster is None or len(users) < len(roster)) else None
        return build_approval_progression((display.get('approvals') or {}).get('funnel'),
            dates, selection, (theme or 0) % 2 == 0)

    @app.callback(Output('approval-progression-chart', 'figure'),
                  Input('dashboard-trend-store', 'data'), Input('selected-users-store', 'data'),
                  Input('theme-toggle', 'n_clicks'), Input('report-location', 'pathname'),
                  State('dashboard-trend-live', 'data'))
    def paint_progression_saved(data, users, theme, pathname, live):
        return progression(data, live, users, theme, pathname)

    @app.callback(Output('approval-progression-chart', 'figure', allow_duplicate=True),
                  Input('dashboard-trend-live', 'data'), State('dashboard-trend-store', 'data'),
                  State('selected-users-store', 'data'), State('theme-toggle', 'n_clicks'),
                  State('report-location', 'pathname'), prevent_initial_call=True)
    def paint_progression_live(live, data, users, theme, pathname):
        if not matching_live(data, live):
            raise dash.exceptions.PreventUpdate
        return progression(data, live, users, theme, pathname)

    return paint_saved, capture, paint_live

"""Saved-first today-submission plot: no task API calls from chart callbacks."""
import dash
from dash import Input, Output

from slicing_dashboard.management.periods import today_iso
from slicing_dashboard.plots.today_submissions_lollipop import (
    build_today_submissions_lollipop,
)
from slicing_dashboard.reporting.daily_output import submission_rework_counts


def saved_today_submission_day(manager, trend=None, today=None):
    """Choose the same verified dated report used by the Daily Report.

    Saved/trend sources can be unavailable during the upstream task-inventory
    403. Never replace missing evidence with current batch or approval hours.
    """
    from slicing_dashboard.reporting.dashboard_reports import day_for_ui
    from slicing_dashboard.reporting.dashboard_trend import work_records
    from slicing_dashboard.reporting.chart_projections import remap_daily_chart
    today = today or today_iso()
    candidate = (trend or {}).get('today', {})
    if (candidate.get('date') == today and
            candidate.get('metadata', {}).get('available') is True):
        return candidate
    try:
        saved = work_records(manager, today, today, local_dates=[today]).get(today)
        if isinstance(saved, dict) and 'chart_rows' in saved:
            saved = {**saved, 'rows': remap_daily_chart(
                saved['chart_rows'], manager._get_reporting_name)}
        return day_for_ui(saved, today, manager._get_reporting_name)
    except (ValueError, KeyError, TypeError, AttributeError):
        return {'date': today, 'rows': [],
                'metadata': {'available': False, 'error': 'DailySourceUnavailable'}}


def register_today_submissions(app, manager):
    @app.callback(
        Output('dashboard-today-submissions-evidence', 'data'),
        Input('report-location', 'pathname'),
        Input('refresh-btn', 'n_clicks'),
        Input('auto-refresh-interval', 'n_intervals'),
        Input('dashboard-trend-store', 'data'),
    )
    def load_today(pathname, _clicks, _intervals, trend):
        if pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        return saved_today_submission_day(manager, trend)

    @app.callback(
        Output('today-submissions-lollipop-chart', 'figure'),
        Input('dashboard-today-submissions-evidence', 'data'),
        Input('selected-users-store', 'data'),
        Input('theme-toggle', 'n_clicks'),
        Input('report-location', 'pathname'),
    )
    def paint_today(day, selected, theme, pathname):
        if pathname not in (None, '/', '/dashboard'):
            raise dash.exceptions.PreventUpdate
        evidence = submission_rework_counts(day, selected, expected_date=today_iso())
        return build_today_submissions_lollipop(evidence, (theme or 0) % 2 == 0)

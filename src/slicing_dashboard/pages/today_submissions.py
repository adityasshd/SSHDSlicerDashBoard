"""Saved-first today-submission plot: no task API calls from chart callbacks."""
import dash
from dash import Input, Output

from slicing_dashboard.management.periods import today_iso
from slicing_dashboard.plots.today_submissions_lollipop import (
    build_today_submissions_lollipop,
)
from slicing_dashboard.reporting.daily_output import (
    submitted_video_output, submitted_status_snapshot,
    select_submitted_status_snapshot,
)


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


def _saved_submitted_status(manager, today):
    """Use only locally saved efficiency evidence, not an extra chart API call.

    It is a submitted STATUS inventory, never an assertion that task
    submissions occurred on the selected date.
    """
    from slicing_dashboard.processing.workflow_history import WorkflowStore
    store = WorkflowStore(manager.db, initialize=False).chart_reader()
    captures = store.records('efficiency-capture', start=today, end=today)
    selected = [capture for capture in captures
                if isinstance(capture, dict) and capture.get('display_date') == today]
    if not selected:
        return {'available': False, 'reason': 'No saved submitted-status snapshot'}
    latest = max(selected, key=lambda capture: str(capture.get('captured_at') or ''))
    return submitted_status_snapshot(latest, manager._get_reporting_name, today)


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
        day = saved_today_submission_day(manager, trend)
        # Prefer real dated submitted video events. If the upstream task
        # history is forbidden or incomplete, show a clearly differentiated
        # submitted-status stock line, with NO inferred rework lollipops.
        if not submitted_video_output(day, expected_date=today_iso()).get('available'):
            try:
                fallback = _saved_submitted_status(manager, today_iso())
                if fallback.get('available'):
                    day = {**day, 'submitted_status_snapshot': fallback}
            except (KeyError, TypeError, ValueError, AttributeError, OSError):
                pass
        return day

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
        evidence = submitted_video_output(day, selected, expected_date=today_iso())
        if not evidence.get('available') and isinstance(day, dict):
            fallback = day.get('submitted_status_snapshot')
            if fallback and fallback.get('available'):
                evidence = select_submitted_status_snapshot(fallback, selected)
        return build_today_submissions_lollipop(evidence, (theme or 0) % 2 == 0)

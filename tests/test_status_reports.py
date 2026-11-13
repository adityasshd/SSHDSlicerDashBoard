"""Status fallback keeps source dates, coverage, and refresh responses separate."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import dash
import pytest

from slicing_dashboard.data_manager import DataManager
from slicing_dashboard.pages.status_report import build_status_report, register_status_reports
from slicing_dashboard.reporting.status_reports import (
    STATUS_FIELDS, get_status_report_data, refresh_status_report, status_payload, summarize_status,
)
from tests.test_daily_report_page import components, payload_text, application_namespace, report_fixture


def day(stamp='2026-10-06', user='Riya', seconds=3600):
    return {'date': stamp, 'rows': [{'User': user, **{field: 0 for field in STATUS_FIELDS},
        'completed_duration_seconds': seconds, 'completed_count': 1 if seconds else 0,
        'submitted_duration_seconds': 1800, 'submitted_count': 2,
        'rework_duration_seconds': 1800, 'rework_count': 2, 'work_duration_seconds': 7200}],
        'metadata': {'available': True, 'captured_at': '2026-10-07T00:00:00+00:00',
                     'timezone': 'Asia/Shanghai'}}


def saved():
    return {**status_payload('2026-10-06', [day('2026-10-05'), day()]),
            'pathname': '/reports/daily', 'request_id': 'new', 'force_refresh': True}


def test_saved_load_requests_full_metrics_without_any_upstream_capture():
    manager = MagicMock()
    manager.get_efficiency_history.return_value = [day()]
    with patch('slicing_dashboard.reporting.status_reports.viewer_mode', return_value=True):
        data = get_status_report_data(manager, '2026-10-06')
    manager.get_efficiency_history.assert_called_once_with(
        '2026-09-07', '2026-10-06', capture_live=False, full_metrics=True)
    assert data['timezone'] == 'Asia/Shanghai'
    assert not data['refresh_pending']
    assert len(data['history']) == 30
    assert data['history'][-1]['rows'][0]['submitted_duration_seconds'] == 1800


def test_full_saved_reader_does_not_use_the_completion_only_projection():
    manager = DataManager.__new__(DataManager)
    history = MagicMock()
    history.read.return_value = [day()]
    history.read_completed.return_value = [{'date': '2026-10-06', 'rows': [], 'metadata': {}}]
    with patch('slicing_dashboard.reporting.efficiency_history.EfficiencyHistory', return_value=history), \
         patch('slicing_dashboard.processing.workflow_history.WorkflowStore'), \
         patch('slicing_dashboard.data_manager.viewer_mode', return_value=True):
        manager.db = None
        full = manager.get_efficiency_history('2026-10-06', '2026-10-06', full_metrics=True)
        compact = manager.get_efficiency_history('2026-10-06', '2026-10-06')
    assert full[0]['rows'][0]['rework_duration_seconds'] == 1800
    assert compact != full
    history.capture.assert_not_called()
    assert len(manager._efficiency_history_cache) == 2


def test_unknown_person_missing_day_and_recorded_zero_are_distinct():
    assert summarize_status(day(seconds=0), 'Riya')['completed_duration_seconds'] == 0
    assert summarize_status(day(), 'Absent')['completed_duration_seconds'] is None
    assert summarize_status({'date': '2026-10-06', 'metadata': {}, 'rows': []})['completed_count'] is None
    malformed = day()
    del malformed['rows'][0]['submitted_duration_seconds']
    assert summarize_status(malformed)['submitted_duration_seconds'] is None
    assert summarize_status(malformed)['completed_duration_seconds'] == 3600


def test_live_checks_two_dates_and_retains_each_failed_day():
    manager = MagicMock()
    data = saved()
    original = deepcopy(data)
    failed = {'date': '2026-10-05', 'rows': [], 'metadata': {'available': False, 'error': 'Failed'}}
    manager.get_efficiency_history.return_value = [failed, day(seconds=7200)]
    with patch('slicing_dashboard.reporting.status_reports.viewer_mode', return_value=False):
        result = refresh_status_report(manager, data)
    manager.get_efficiency_history.assert_called_once_with('2026-10-05', '2026-10-06',
                                                          force_refresh=True, full_metrics=True)
    assert data == original
    assert result['history'][-1]['rows'][0]['completed_duration_seconds'] == 7200
    assert result['history'][-2]['rows'][0]['completed_duration_seconds'] == 3600
    assert result['history'][-2]['metadata']['error'] == 'StatusRefreshFailed'
    assert result['request_id'] == 'new'
    assert not result['refresh_pending']


def test_viewer_does_not_refresh_even_if_client_supplies_pending_request():
    manager = MagicMock()
    with patch('slicing_dashboard.reporting.status_reports.viewer_mode', return_value=True):
        result = refresh_status_report(manager, saved())
    assert not result['refresh_pending']
    manager.get_efficiency_history.assert_not_called()


def test_page_shows_three_independent_video_metrics_and_separate_activity_time():
    panel = build_status_report(saved())
    text = payload_text(panel)
    assert 'UTC+08' in text and '21:30' in text
    assert '01:00:00' in text and '00:30:00' in text and '02:00:00' in text
    assert 'do not add these cards together' in text
    assert 'Fresh work and same-day rework cannot be determined' in text
    graph = next(c for c in components(panel) if getattr(c, 'id', None) == 'daily-status-trend')
    assert len(graph.figure.data) == 3
    assert all(trace.connectgaps is False and trace.y[0] is None for trace in graph.figure.data)
    assert graph.figure.data[0].y[-1] == 1
    assert graph.figure.data[1].y[-1] == .5
    individual = payload_text(build_status_report(saved(), 'Absent', kind='user'))
    assert 'no account rows' in individual
    assert '01:00:00' not in individual


def test_late_live_response_cannot_replace_newer_date_or_route_and_theme_does_not_fetch():
    manager = MagicMock()
    load, render, live, render_live = register_status_reports(dash.Dash(__name__), manager)
    data = saved()
    old = {**data, 'request_id': 'old', 'history': [day('2026-10-05', seconds=9999), day(seconds=9999)]}
    current, hidden, request, painted = render(data, old, 1, None, '/reports/daily', data)
    assert hidden is dash.no_update and request is dash.no_update
    assert '01:00:00' in payload_text(current)
    assert '02:46:39' not in payload_text(current)
    current, hidden = render_live(old, None, painted, data, 1, '/reports/daily')
    assert hidden is dash.no_update
    assert '01:00:00' in payload_text(current)
    assert '02:46:39' not in payload_text(current)
    with pytest.raises(dash.exceptions.PreventUpdate):
        render(data, None, 0, None, '/reports/user', None)
    with pytest.raises(dash.exceptions.PreventUpdate):
        live(data, '/')
    with pytest.raises(dash.exceptions.PreventUpdate):
        render_live(data, None, painted, data, 1, '/reports/user')
    with pytest.raises(dash.exceptions.PreventUpdate):
        render_live(data, None, {**painted, 'request_id': 'old'}, data, 1, '/reports/daily')
    manager.get_efficiency_history.assert_not_called()


def test_saved_status_paints_before_refresh_and_person_changes_only_render():
    manager = MagicMock()
    app = dash.Dash(__name__)
    _, render, _, render_live = register_status_reports(app, manager)
    data = {**saved(), 'pathname': '/reports/user', 'refresh_pending': True}
    hidden, panel, request, painted = render(data, None, 0, 'Riya', '/reports/user', None)
    assert hidden is dash.no_update and request == data
    assert '01:00:00' in payload_text(panel)
    paint_callback = next(cb for key, cb in app.callback_map.items()
                          if 'report-status-request.data' in key)
    assert not {'report-status-live', 'user-report-person'} & {
        item['id'] for item in paint_callback['inputs']}
    latest = {**data, 'refresh_pending': False,
              'history': [day('2026-10-05'), day(seconds=7200)]}
    _, panel = render_live(latest, 'Riya', painted, data, 0, '/reports/user')
    assert '02:00:00' in payload_text(panel)
    _, panel = render_live(latest, 'Absent', painted, data, 0, '/reports/user')
    assert 'no account rows' in payload_text(panel)
    _, panel, request, _ = render(data, latest, 1, 'Riya', '/reports/user', data)
    assert request is dash.no_update and '02:00:00' in payload_text(panel)
    manager.get_efficiency_history.assert_not_called()


def test_report_route_reads_saved_submissions_and_exposed_status_only():
    namespace, manager = application_namespace()
    data = {**report_fixture(), 'refresh_pending': True}
    manager.get_saved_daily_report_data.return_value = data
    with patch('dash.callback_context', MagicMock(triggered=[{'prop_id': 'refresh-btn.n_clicks'}])):
        result = namespace['load_daily_report']('/reports/daily', 1, 0, '2026-10-06')
    assert not result['refresh_pending']
    manager.get_daily_report_data.assert_not_called()
    status = {**saved(), 'users': ['Riya', 'New member']}
    options, selection = namespace['update_report_people'](report_fixture(), 'Riya', status)
    assert selection is dash.no_update
    assert 'New member' in {row['value'] for row in options}


def test_bad_or_future_report_date_rejected_before_read():
    manager = MagicMock()
    for value in ('invalid', '2099-01-01'):
        with pytest.raises(ValueError):
            get_status_report_data(manager, value)
    manager.get_efficiency_history.assert_not_called()

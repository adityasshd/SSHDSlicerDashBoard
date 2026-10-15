"""The Vercel dashboard must never collect or republish upstream evidence."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import dash
from flask import Flask
import httpx
import pytest

from slicing_dashboard.runtime import viewer_mode
from slicing_dashboard.data_manager import DataManager
from slicing_dashboard.reporting.data_health import register_data_health_routes
from slicing_dashboard.reporting.completed_work import completed_work_for_period
from slicing_dashboard.viewer import refresh_saved_state, register_viewer_routes
from tests.test_daily_report_page import application_namespace, components


@pytest.fixture
def viewer(monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('DASHBOARD_ROLE', 'collector')  # Cannot bypass Vercel isolation.
    monkeypatch.setenv('CRON_SECRET', 'fixture-secret')


def test_vercel_cannot_be_switched_to_collector(viewer):
    assert viewer_mode()


def test_real_scraper_rejects_http_before_transport(viewer, monkeypatch):
    from slicing_dashboard.config import Settings
    from slicing_dashboard.scraper.http_scraper import HTTPScraper
    client_class = httpx.Client
    transport = MagicMock(return_value=httpx.Response(200))
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client_class(
        **kwargs, transport=httpx.MockTransport(transport)))
    scraper = HTTPScraper(Settings(admin_username='fixture', admin_password=''))
    with scraper._client:
        with pytest.raises(RuntimeError, match='disabled'):
            scraper._client.get('https://fixture.invalid/api/tasks')
    transport.assert_not_called()


@pytest.mark.parametrize('path', ['/api/data-refresh', '/api/data-jobs/enqueue',
                                  '/api/data-jobs/run', '/api/data-jobs/fail'])
def test_capture_routes_fail_before_creating_services(viewer, path):
    server = Flask(__name__)
    register_data_health_routes(server, object())
    with patch('slicing_dashboard.reporting.data_health.DataHealth') as service:
        client = server.test_client()
        assert client.post(path).status_code == 401
        response = client.post(path, headers={'Authorization': 'Bearer fixture-secret'})
        assert response.status_code == 410
        assert response.json['error'] == 'CollectionDisabled'
        service.assert_not_called()


def test_viewer_has_no_ticking_intervals_or_live_panel_reads(viewer):
    namespace, manager = application_namespace()
    intervals = [node for node in components(namespace['app'].layout)
                 if isinstance(node, dash.dcc.Interval)]
    assert {node.id for node in intervals} >= {
        'auto-refresh-interval', 'heartbeat-interval', 'workflow-notification-interval'}
    assert all(node.disabled for node in intervals)
    callbacks = namespace['app'].callback_map
    for store in ('dashboard-live-completion', 'dashboard-trend-live'):
        callback = next(value for key, value in callbacks.items() if key == f'{store}.data')
        with pytest.raises(dash.exceptions.PreventUpdate):
            callback['callback'].__wrapped__({}, {})
    manager.get_efficiency_history.assert_not_called()
    manager.get_user_breakdown_df.assert_not_called()


def test_daily_saved_view_does_not_schedule_a_scan(viewer):
    from slicing_dashboard.reporting.dashboard_reports import get_saved_daily_report_data
    from slicing_dashboard.management.periods import today_iso
    manager = MagicMock(user_mapping={}, user_mapping_full={}, _snapshot_payload={})
    manager._saved_daily_report_cache = {}
    with patch('slicing_dashboard.reporting.dashboard_trend.work_records', return_value={}):
        data = get_saved_daily_report_data(manager, today_iso(), True)
    assert data['refresh_pending'] is False
    assert data['saved_only'] is True
    manager.get_todays_work_df.assert_not_called()


def test_expired_completion_is_read_without_login_or_snapshot_write(viewer):
    manager = MagicMock()
    manager._cache = {'completed_report_2026-10-01_2026-10-14': {
        'start': '2026-10-01', 'end': '2026-10-14', 'captured_at': '2026-10-14T00:00:00+00:00',
        'items': [{'user_id': 1, 'username': 'Riya', 'completed_duration_seconds': 3600,
                   'completed_count': 2}]}}
    manager._get_reporting_name.side_effect = lambda uid, name: name
    result = completed_work_for_period(manager, '2026-10-01', '2026-10-14', True)
    assert result['available'] and result['is_snapshot']
    assert result['rows'] == [{'User': 'Riya', 'seconds': 3600, 'tasks': 2}]
    manager.scraper.login.assert_not_called()
    manager.scraper._client.get.assert_not_called()
    manager._save_snapshot.assert_not_called()


def test_no_saved_completion_does_not_become_zero(viewer):
    manager = MagicMock(_cache={})
    assert completed_work_for_period(manager, '2026-10-01', '2026-10-14', True)['available'] is False
    manager.scraper.login.assert_not_called()


def test_snapshot_publication_is_disabled(viewer):
    manager = DataManager.__new__(DataManager)
    manager.db = MagicMock()
    DataManager._save_snapshot(manager)
    manager.db.save_dashboard_snapshot.assert_not_called()


def saved_manager():
    return SimpleNamespace(db=MagicMock(), _snapshot_payload={'last_sync_time': 'old'},
        _cache={}, refresh_shared_configuration=MagicMock())


def test_refresh_burst_shares_database_read_and_invalidates_prepared_reports(viewer):
    manager = saved_manager()
    snapshot = {'last_sync_time': 'new', 'cache': {'overview': {'count': 10}},
                'batches_master_records': [], 'batch_returns_records': []}
    manager.db.load_dashboard_snapshot.return_value = deepcopy(snapshot)
    manager._user_report_cache = {'old': 'old data'}
    with patch('slicing_dashboard.viewer.perf_counter', return_value=1000):
        for _ in range(12):
            refresh_saved_state(manager, force=True)
    manager.db.load_dashboard_snapshot.assert_called_once_with()
    assert manager._snapshot_payload == snapshot
    assert manager._cache['overview']['count'] == 10
    assert not hasattr(manager, '_user_report_cache')
    manager.db.save_dashboard_snapshot.assert_not_called()


def test_failed_reload_keeps_previous_capture_and_reports_error(viewer):
    manager = saved_manager()
    manager.db.load_dashboard_snapshot.return_value = None
    refresh_saved_state(manager, force=True)
    assert manager._snapshot_payload == {'last_sync_time': 'old'}
    assert manager._viewer_storage_error


def test_invalid_reload_cannot_partially_replace_good_state(viewer):
    manager = saved_manager()
    manager.db.load_dashboard_snapshot.return_value = {'last_sync_time': 'bad', 'cache': None}
    refresh_saved_state(manager, force=True)
    assert manager._snapshot_payload == {'last_sync_time': 'old'}
    assert manager._cache == {}
    assert manager._viewer_storage_error


def test_collector_commit_can_differ_from_viewer_commit(viewer, monkeypatch):
    from slicing_dashboard.reporting.data_health import DataHealth, SOURCES, PROCESSOR_VERSION, utc_now
    monkeypatch.setenv('VERCEL_GIT_COMMIT_SHA', 'viewer-commit')
    manager = SimpleNamespace(settings=SimpleNamespace(mongo_uri='fixture', database_url=None,
                              admin_username='fixture'), db=MagicMock(),
                              scraper=SimpleNamespace(_base_url='https://fixture.invalid'))
    store = MagicMock()
    store.get.return_value = {'sources': {name: {'last_success_at': utc_now().isoformat(),
        'processor_version': PROCESSOR_VERSION, 'build': 'separate-collector-commit'} for name in SOURCES}}
    assert DataHealth(manager, store).health()['ok']


def test_only_static_code_is_publicly_cacheable(viewer):
    server = Flask(__name__)
    register_viewer_routes(server, saved_manager())
    server.add_url_rule('/_dash-component-suites/dash/hash.js', 'script', lambda: 'script')
    server.add_url_rule('/_dash-layout', 'layout', lambda: 'private report')
    client = server.test_client()
    assert 's-maxage' in client.get('/_dash-component-suites/dash/hash.js').headers['Vercel-CDN-Cache-Control']
    response = client.get('/_dash-layout')
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'Vercel-CDN-Cache-Control' not in response.headers

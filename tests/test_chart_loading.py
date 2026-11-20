"""Plots must not wait for unrelated captures or download full task evidence."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, patch

import dash
from slicing_dashboard.data_manager import DataManager
from slicing_dashboard.db import DatabaseManager
from tests.test_daily_report_page import application_namespace


def test_lead_lollipop_uses_existing_completion_and_pending_captures():
    namespace, manager = application_namespace()
    callbacks = namespace['app'].callback_map
    completion = next(key for key in callbacks
                      if 'individual-chart.figure' in key and '@' not in key)
    pending = next(key for key in callbacks if 'pending-chart.figure' in key)
    assert 'dashboard-trend-store.data' not in callbacks
    assert not any('approval-trend-chart.figure' in key for key in callbacks)
    capture_inputs = {item['id'] for item in callbacks[completion]['inputs']}
    assert {'dashboard-panel-request', 'dashboard-saved-completion',
            'dashboard-pending-request', 'dashboard-saved-pending',
            'dashboard-live-pending'} <= capture_inputs
    for key in (completion, pending):
        assert 'workflow-sync-store' not in {
            item['id'] for item in callbacks[key]['inputs']}
    selection = next(value for key, value in callbacks.items()
                     if 'selected-users-store.data' in key)
    assert {item['id'] for item in selection['inputs']} == {
        'universal-legend', 'individual-chart'}
    assert {'id': 'universal-legend', 'property': 'value'} in selection['inputs']
    from tests.test_daily_report_page import components
    ids = [getattr(node, 'id', None) for node in components(namespace['app'].layout)]
    assert ids.count('individual-chart') == ids.count('universal-legend') == 1
    assert 'approval-trend-chart' not in ids
    manager.get_dashboard_trend_data.assert_not_called()



def test_team_legend_checkboxes_filter_every_dashboard_visual():
    from tests.test_daily_report_page import components
    from unittest.mock import patch
    namespace, manager = application_namespace()
    app = namespace['app']
    roster = namespace['available_users']
    assert len(roster) >= 2
    options = next(node for node in components(app.layout)
                   if getattr(node, 'id', None) == 'universal-legend')
    assert isinstance(options, dash.dcc.Checklist)
    assert options.value == roster
    assert [option['value'] for option in options.options] == roster
    selected_callback = next(value for key, value in app.callback_map.items()
                             if 'selected-users-store.data' in key)
    assert {'id': 'universal-legend', 'property': 'value'} in selected_callback['inputs']
    select = selected_callback['callback'].__wrapped__
    with patch('dash.ctx', MagicMock(triggered_id='universal-legend')):
        selection, echo = select([roster[0]], None, roster)
    assert selection == [roster[0]]
    assert echo is dash.no_update  # No feedback loop on checkbox changes.
    with patch('dash.ctx', MagicMock(triggered_id='individual-chart')):
        selection, echo = select([roster[0]], {'points': [{'x': roster[0]}]},
                                 [roster[0]])
    assert selection == echo == []  # Markers also synchronize the checkboxes.

    # Every dashboard panel must subscribe to the same selected-user store.
    for output in ('individual-chart.figure', 'pending-chart.figure',
                   'rework-ratio-chart.figure', 'assigned-chart.figure',
                   'review-workload-chart.figure',
                   'today-submissions-lollipop-chart.figure',
                   'return-reasons-chart.figure'):
        callbacks = [item for key, item in app.callback_map.items() if output in key]
        assert callbacks and any(
            {'id': 'selected-users-store', 'property': 'data'} in callback['inputs']
            for callback in callbacks), output
    manager.get_user_breakdown_df.assert_not_called()


def test_saved_line_range_cache_and_single_day_selection(tmp_path):
    manager = DataManager.__new__(DataManager)
    manager.db = MagicMock()
    manager.user_mapping = {}
    manager.user_mapping_full = {}
    manager.db.load_daily_chart_reports.return_value = []
    manager.get_approval_data = MagicMock(return_value={})
    manager.get_efficiency_history = MagicMock(return_value=[])
    with patch('slicing_dashboard.config.DATA_DIR', tmp_path), \
         patch('slicing_dashboard.reporting.dashboard_trend.today_iso', return_value='2026-10-06'):
        first = manager.get_dashboard_trend_data('2026-10-06', start_date='2026-10-01')
        second = manager.get_dashboard_trend_data('2026-10-06', start_date='2026-10-02')
        assert len(first['history']) == 6 and len(second['history']) == 5
        manager.db.load_daily_chart_reports.assert_called_with('2026-10-02', '2026-10-06')
        day = manager.get_dashboard_trend_data('2026-10-06', start_date='2026-10-06')
        assert len(day['history']) == 1 and day['previous_date'] == '2026-10-05'


def test_chart_projection_omits_audit_fields_and_preserves_remapping():
    database = DatabaseManager.__new__(DatabaseManager)
    collection = MagicMock()
    collection.with_options.return_value = collection
    database.mongo_db = {'daily_work_reports': collection}
    collection.find.return_value.batch_size.return_value = []
    assert database.load_daily_chart_reports('2026-10-01', '2026-10-06') == []
    query, fields = collection.find.call_args.args
    assert query['_id'] == {'$gte': '2026-10-01', '$lte': '2026-10-06'}
    assert fields['tasks.username'] == fields['tasks.bucket'] == fields['tasks.duration_seconds'] == 1
    assert 'tasks' not in fields and 'tasks.submitted_at' not in fields
    assert collection.find.call_args_list[0].args[1]['chart_rows'] == 1


def test_saved_line_reads_overlap_do_not_wait_for_daily_capture_and_remap_aliases():
    manager = DataManager.__new__(DataManager)
    manager.user_mapping = {'one': 'Person', 'two': 'Person'}
    manager.user_mapping_full = {}
    manager.db = MagicMock()
    day = {'date': '2026-10-06', 'metadata': {'available': True}, 'tasks': [
        {'username': 'one', 'user_id': 1, 'bucket': 'Fresh', 'duration_seconds': 3600},
        {'username': 'two', 'user_id': 2, 'bucket': 'Same-day Rework', 'duration_seconds': 1800}]}
    work_started, approvals_started, efficiency_started = Event(), Event(), Event()
    def work(*args):
        work_started.set()
        assert approvals_started.wait(1) and efficiency_started.wait(1)
        return [day]
    def approvals(*args):
        approvals_started.set()
        assert work_started.wait(1)
        return {'rows': []}
    def efficiency(*args, **kwargs):
        efficiency_started.set()
        assert kwargs == {'capture_live': False}
        assert work_started.wait(1)
        return []
    manager.db.load_daily_chart_reports.side_effect = work
    manager.get_approval_data = MagicMock(side_effect=approvals)
    manager.get_efficiency_history = MagicMock(side_effect=efficiency)
    manager.get_todays_work_df = MagicMock(side_effect=AssertionError('Live inventory scan'))
    with patch('slicing_dashboard.management.periods.today_iso', return_value='2026-10-06'), \
         patch('slicing_dashboard.reporting.dashboard_trend.today_iso', return_value='2026-10-06'):
        # The existing slow daily capture owns its payload lock in another thread.
        from slicing_dashboard.data_manager import _DAILY_PAYLOAD_LOCK
        with ThreadPoolExecutor(max_workers=1) as pool:
            with _DAILY_PAYLOAD_LOCK:
                payload = pool.submit(manager.get_dashboard_trend_data, '2026-10-06').result(timeout=2)
        assert payload['today']['rows'][0]['Total Duration'] == 5400
        assert len(payload['today']['rows']) == 1
        payload['history'].clear()
        assert len(manager.get_dashboard_trend_data('2026-10-06')['history']) == 30
    manager.db.load_daily_chart_reports.assert_called_once()
    manager.get_todays_work_df.assert_not_called()


def test_compact_daily_rows_match_task_evidence_after_alias_split_and_exclusions():
    from slicing_dashboard.reporting.chart_projections import daily_chart_rows, remap_daily_chart
    from slicing_dashboard.reporting.dashboard_reports import aggregate_observations
    tasks = [{'username': account, 'bucket': bucket, 'duration_seconds': seconds}
             for account, bucket, seconds in [('a', 'Fresh', 3600), ('b', 'Same-day Rework', 1800),
                                               ('a', 'Old Rework', 900), ('excluded', 'Fresh', 500),
                                               ('Admin', 'Fresh', 300)]]
    compact = daily_chart_rows({'tasks': tasks})
    for aliases in ({'a': 'Person', 'b': 'Person', 'excluded': 'Exempt', 'Admin': 'Person'},
                    {'a': 'Person', 'b': 'Other', 'excluded': 'Exempt', 'Admin': 'Exempt'}):
        resolver = lambda uid, name: aliases.get(name, name)
        assert remap_daily_chart(compact, resolver) == aggregate_observations(tasks, resolver)


def test_compact_workflow_fields_preserve_completion_and_approval_totals():
    from copy import deepcopy
    from slicing_dashboard.reporting.chart_projections import workflow_chart
    from slicing_dashboard.reporting.approval_reports import approval_records
    event = {'id': 'approved-one', 'source': 'batch-review', 'action': 'Approved', 'active': True,
             'event_at': '2026-10-06T04:00:00Z', 'member': 'Person', 'stage': 'Leader',
             'batch_id': 'ab_one', 'cycle': 1, 'batch_video_seconds_at_capture': 3600,
             'raw': {'large_audit': 'preserved'}, 'provenance': 'Observed'}
    original = deepcopy(event)
    compact = workflow_chart('event', event)
    assert 'raw' not in compact and event == original
    assert approval_records([compact]) == approval_records([event])


def test_chart_replica_preference_never_changes_writer_database():
    from pymongo import ReadPreference
    from slicing_dashboard.processing.workflow_history import WorkflowStore
    primary, replica = MagicMock(), MagicMock()
    primary.with_options.return_value = replica
    store = WorkflowStore.__new__(WorkflowStore)
    store.mongo = primary
    reader = store.chart_reader()
    assert store.mongo is primary and reader.mongo is replica
    primary.with_options.assert_called_once_with(read_preference=ReadPreference.SECONDARY_PREFERRED)


def test_failed_chart_read_retains_memory_and_labels_local_evidence(tmp_path):
    import json
    from slicing_dashboard.reporting.dashboard_trend import work_records
    manager = DataManager.__new__(DataManager)
    manager.db = MagicMock()
    manager.db.load_daily_chart_reports.side_effect = RuntimeError('Unavailable')
    manager._daily_report_records = {'2026-10-05': {'date': '2026-10-05', 'rows': []}}
    directory = tmp_path / 'reports' / 'daily-work'
    directory.mkdir(parents=True)
    record = {'date': '2026-10-06', 'rows': [{'User': 'Person', 'Total Duration': 3600}],
              'metadata': {'available': True}}
    (directory / '2026-10-06.json').write_text(json.dumps(record))
    with patch('slicing_dashboard.config.DATA_DIR', tmp_path):
        retained = work_records(manager, '2026-09-07', '2026-10-06')
    assert retained['2026-10-06']['rows'] == record['rows']
    assert all(day['metadata']['is_snapshot'] and day['metadata']['error'] == 'DailyChartReadFailed'
               for day in retained.values())
    assert 'metadata' not in manager._daily_report_records['2026-10-05']

"""Phase 3 parity, coverage and callback ownership without upstream access."""
from unittest.mock import MagicMock, patch
from collections import defaultdict

import dash
import pandas as pd
import pytest

from slicing_dashboard.reporting.approval_reports import prepare_approval_trend, approval_records
from slicing_dashboard.plots.approval_trend_chart import build_approval_trend_chart
from tests.test_daily_report_page import application_namespace, components, report_fixture


def fixture():
    data = report_fixture(rows=[
        {'User': 'Priya', 'Total Duration': 3600, 'Total Tasks': 1},
        {'User': 'Riya', 'Total Duration': 1800, 'Total Tasks': 1},
    ])
    data['history'][-2]['metadata']['available'] = True
    data['efficiency_history'] = [
        {'date': day['date'], 'metadata': day['metadata'],
         'rows': [{'User': row['User'], 'completed_duration_seconds': row['Total Duration']}
                  for row in day['rows']]} for day in data['history']]
    return data


def test_trend_preserves_submission_parity_zero_and_missing_days():
    report = prepare_approval_trend(fixture())
    assert len(report['rows']) == 30
    assert report['rows'][0]['total_seconds'] is None
    assert report['rows'][-2]['total_seconds'] == 0
    assert report['rows'][-1]['total_seconds'] == 5400
    assert report['recorded_days'] == 2
    assert prepare_approval_trend(fixture(), ['Riya'])['rows'][-1]['total_seconds'] == 1800
    # Unknown workflow fields and current-state queues cannot become throughput.
    data = fixture()
    data.update(transitions=[{'type': 'AdminApproved', 'duration': 7200}],
                leader_review_duration=9000, workflow_events=[{'review_decision': 'approved'}])
    rows = prepare_approval_trend(data)['rows']
    for field in ('leader_seconds', 'auditor_seconds', 'admin_seconds'):
        assert all(row[field] is None for row in rows)


def test_chart_gaps_units_themes_and_approval_labels():
    report = prepare_approval_trend(fixture())
    for dark in (True, False):
        figure = build_approval_trend_chart(report, dark)
        assert figure.data[0].y[-1] == 1.5
        assert figure.data[0].y[-2] == 0
        assert figure.data[0].y[0] is None
        assert all(not trace.connectgaps for trace in figure.data)
        assert all(trace.fill == 'tozeroy' for trace in figure.data[:4])
        assert all('unavailable' in trace.name for trace in figure.data[1:4])
        assert all(all(value is None for value in trace.y) for trace in figure.data[1:4])
        assert figure.data[-1].name == 'New submissions'
        assert figure.data[-1].fill == 'none'
        assert '01:30:00' == figure.data[0].customdata[-1]
        figure.to_json()


def test_new_submission_series_preserves_person_filters_missing_days_and_zero():
    data = report_fixture(rows=[
        {'User': 'Priya', 'Total Duration': 3600, 'New Videos (First Time)': 2400,
         'Same-day Rework': 1200, 'Old Rework': 600},
        {'User': 'Riya', 'Total Duration': 1800, 'New Videos (First Time)': 1800},
    ])
    data['history'][-2]['metadata']['available'] = True
    report = prepare_approval_trend(data, ['Priya'])
    assert report['rows'][-1]['total_seconds'] == 3600
    assert report['rows'][-1]['new_seconds'] == 2400
    assert report['rows'][-2]['new_seconds'] == 0
    assert report['rows'][0]['new_seconds'] is None
    assert report['latest_submission_date'] == '2026-10-06'
    figure = build_approval_trend_chart(report)
    new = next(trace for trace in figure.data if trace.name == 'New submissions')
    assert list(new.y)[-2:] == [0, 2400 / 3600]
    assert new.y[0] is None and new.connectgaps is False


def test_dashboard_cleanup_retains_reports_and_management():
    namespace, _ = application_namespace()
    by_id = {getattr(node, 'id', None): node for node in components(namespace['app'].layout)}
    assert 'error-rework-chart' not in by_id
    assert 'approval-trend-chart' not in by_id
    assert 'individual-chart' in by_id
    assert 'approval-outcomes-chart' not in by_id
    assert by_id['main-container'].className == 'theme-dark'
    assert by_id['theme-toggle'].n_clicks == 0
    assert 'daily-report-page' in by_id and 'user-report-page' in by_id
    assert 'tabs' not in by_id and 'tabs-content' not in by_id
    assert 'settings-page' in by_id
    settings = by_id['settings-tabs']
    assert {tab.tab_id for tab in settings.children} == {'settings-settlement', 'settings-mapping'}
    ids = {'rework-ratio-chart', 'individual-chart', 'pending-chart', 'assigned-chart'}
    assert ids <= by_id.keys()
    callback_ids = {entry['id'] for callback in namespace['app'].callback_map.values()
                    for entry in callback['inputs']}
    assert 'error-rework-chart' not in callback_ids


def test_retired_trend_data_remains_pure_and_handles_user_filters():
    # The historical chart was removed from the dashboard, but its report
    # calculations remain independently testable for report consumers.
    namespace, manager = application_namespace()
    for selection in (['Priya'], ['Priya', 'Riya']):
        for dark in (True, False):
            report = prepare_approval_trend(fixture(), selection)
            figure = build_approval_trend_chart(
                report, dark, primary_only=True, primary_metric='completed')
            assert figure.data[0].y[-1] == (1 if len(selection) == 1 else 1.5)
            assert report['calendar_days'] == 30
            assert figure.data[0].y[0] is None
            assert not figure.data[0].connectgaps
    manager.get_daily_report_data.assert_not_called()
    manager.get_todays_work_df.assert_not_called()
    assert 'dashboard-trend-store.data' not in namespace['app'].callback_map


def test_persisted_batch_stages_supply_filtered_area_series_and_honest_gaps():
    def event(identifier, stage, seconds=3600, **kwargs):
        return {'id': identifier, 'source': 'batch-review', 'action': 'Approved', 'active': True,
                'batch_id': 'ab_' + identifier, 'cycle': 'initial', 'stage': stage,
                'member': 'Priya', 'event_at': '2026-10-06T01:00:00+08:00',
                'batch_video_seconds_at_capture': seconds, **kwargs}
    events = [event('l', 'Leader'), event('a', 'Auditor', 1800, member='Riya'),
              event('admin', 'Admin', 7200),
              event('synthetic', 'Leader', is_synthetic=True, event_at=None),
              event('clip', 'Leader', source='task-review'), event('inactive', 'Auditor', active=False)]
    payload = approval_records(events)
    report = prepare_approval_trend(fixture(), approvals=payload)
    # Midnight boundary: Shanghai 01:00 is previous day in India.
    row = report['rows'][-2]
    assert (row['leader_seconds'], row['auditor_seconds'], row['admin_seconds']) == (3600, 1800, 7200)
    assert report['rows'][-1]['leader_seconds'] is None
    assert 'estimate' in report['approval_status'] and 'incomplete' in report['approval_status']
    filtered = prepare_approval_trend(fixture(), ['Priya'], payload)
    assert filtered['rows'][-2]['auditor_seconds'] is None
    namespace, manager = application_namespace()
    # The dashboard now uses the effective-work lollipop, so the historical
    # completion line is tested as a standalone, non-mounted report builder.
    selected = prepare_approval_trend(fixture(), approvals=payload)
    figure = build_approval_trend_chart(
        selected, True, primary_only=True, primary_metric='completed')
    assert all('unavailable' not in trace.name for trace in figure.data)
    assert len(figure.data) == 1
    assert figure.data[0].name == 'Completed video'
    assert figure.data[0].line.shape == 'spline'
    # Detailed approval evidence remains available to report consumers.
    assert build_approval_trend_chart(report).data[1].y[-2] == 1
    assert 'estimate' in report['approval_status']
    manager.get_workflow_data.assert_not_called()


def test_dated_approval_duration_missing_never_shows_partial_day_or_fake_zero():
    events = [{'id': 'a', 'source': 'batch-review', 'action': 'Approved', 'active': True,
               'batch_id': 'ab_a', 'cycle': 'initial', 'stage': 'Leader', 'member': 'Priya',
               'event_at': '2026-10-05T12:00:00+08:00', 'provenance': 'Stage inferred'},
              {'id': 'b', 'source': 'batch-review', 'action': 'Approved', 'active': True,
               'batch_id': 'ab_b', 'cycle': 'initial', 'stage': 'Leader', 'member': 'Priya',
               'event_at': '2026-10-05T13:00:00+08:00', 'batch_video_seconds_at_capture': 3600}]
    checkpoints = [{'source': 'batch-review', 'last_complete_at': '2026-10-06T12:00:00Z'}]
    report = prepare_approval_trend(fixture(), approvals=approval_records(events, checkpoints=checkpoints))
    assert report['rows'][-2]['leader_seconds'] is None
    assert report['rows'][-1]['leader_seconds'] == 0
    assert report['rows'][0]['leader_seconds'] is None
    assert 'lack batch duration' in report['approval_status']
    assert 'approval-order' in report['approval_status']


def test_same_batch_stage_cycle_is_counted_once_and_later_cycle_is_distinct():
    base = {'source': 'batch-review', 'action': 'Approved', 'active': True, 'batch_id': 'ab_a',
            'cycle': 'initial', 'stage': 'Leader', 'member': 'Priya', 'event_at': '2026-10-06T12:00:00+08:00'}
    events = [{**base, 'id': 'duplicate'}, {**base, 'id': 'first'},
              {**base, 'id': 'reapproval', 'cycle': 'after:return'}]
    payload = approval_records(events, [{'batch_id': 'ab_a', 'total_duration_seconds': 3600}])
    assert len(payload['rows']) == 2
    assert prepare_approval_trend(fixture(), approvals=payload)['rows'][-1]['leader_seconds'] == 7200


def test_source_refresh_loads_once_and_editor_content_stays_mounted():
    namespace, manager = application_namespace()
    manager.get_daily_report_data.return_value = fixture()
    manager.get_dashboard_trend_data.return_value = {**fixture(), 'approvals': {}, 'efficiency_history': []}
    manager.fetch_dashboard_data.return_value = {'breakdowns': {'slice_funnel': []}}
    manager.get_summary_kpis.return_value = defaultdict(int)
    manager.get_user_breakdown_df.return_value = pd.DataFrame()
    manager.get_batch_rework_ratio_df.return_value = pd.DataFrame()
    manager.get_detailed_pending_assigned_df.return_value = pd.DataFrame()
    namespace['_build_status_banner'] = MagicMock()
    namespace['_build_status_badge'] = MagicMock()
    mounted = {getattr(node, 'id', None): node for node in components(namespace['app'].layout)}
    editor = mounted['settings-mapping-panel'].children
    with patch('dash.callback_context', MagicMock(triggered=[{'prop_id': 'refresh-btn.n_clicks'}])):
        result = namespace['update_dashboard'](
            1, 1, '2026-10-01', '2026-10-06', None, 0, 'tab-manage-mapping', None, ['Priya', 'Riya'])
    assert mounted['settings-mapping-panel'].children is editor
    manager.get_daily_report_data.assert_not_called()
    manager.get_slice_data_overview_df.assert_not_called()
    # Removing the redundant top trend must also remove its extra refresh
    # capture, leaving the separately captured duration panels intact.
    assert 'dashboard-trend-store.data' not in namespace['app'].callback_map
    manager.get_daily_report_data.assert_not_called()
    manager.get_dashboard_trend_data.assert_not_called()
    manager.prepare_daily_work.assert_not_called()


def test_removed_overview_has_no_callback_dependency():
    namespace, manager = application_namespace()
    for callback in namespace['app'].callback_map.values():
        assert 'tabs' not in {entry['id'] for entry in callback['inputs']}
    assert '_render_tab' not in namespace

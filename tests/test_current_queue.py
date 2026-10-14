from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from slicing_dashboard.data_manager import DataManager
from slicing_dashboard.processing.current_queue import fetch_queue
from slicing_dashboard.processing.current_queue import assignment_metadata
from slicing_dashboard.plots.assigned_chart import build_assigned_chart


def manager():
    dm = DataManager.__new__(DataManager)
    dm._cache = {'live_slice_assigned': {'Aditya': {'backlog_dur': 7461}}}
    dm._batches_master_cache = {'old': {'batch_id': 'old', 'username': 'SSHD-S-Aditya3',
        'status': 'batch_member_assigned', 'total_duration_seconds': 7461, 'task_count': 67}}
    dm.scraper = MagicMock(is_authenticated=True)
    dm.scraper._users = {1: {}}
    dm._get_reporting_name = lambda uid, name: 'Aditya'
    dm.fetch_annotator_efficiency = MagicMock(return_value=({}, []))
    # Assignment tests isolate their two queues from the independent review read.
    dm.get_pending_review_df = MagicMock(return_value=pd.DataFrame())
    return dm


def task(identifier, duration, account='SSHD-S-Aditya3', status='slice_assigned'):
    return {'id': identifier, 'slicer_id': 1, 'slicer': account, 'status': status, 'duration_seconds': duration}


def test_submitted_account_does_not_reappear_from_ledger_or_snapshot():
    dm = manager()
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', return_value=[]):
        frame = dm.get_detailed_pending_assigned_df(overview_data={}, force_refresh=True)
    assert frame[frame.Stage.isin(['New Assigned', 'Rework Assigned'])].empty
    assert not frame.attrs['assignment_errors']
    assert build_assigned_chart(frame[frame.Stage == 'New Assigned'], True).layout.annotations[0].text == 'No assigned work active'


def test_current_assignments_keep_accounts_and_rework_separate():
    dm = manager()
    inventories = [[task('a', 60), task('b', 120, 'OtherAccount')],
                   [task('c', 90, status='slice_rework')]]
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=inventories):
        frame = dm.get_detailed_pending_assigned_df(overview_data={})
    rows = frame[frame.Stage.isin(['New Assigned', 'Rework Assigned'])]
    assert len(rows) == 3
    assert rows[rows.Stage == 'New Assigned'].Duration.sum() == 180
    assert rows[rows.Stage == 'Rework Assigned'].Duration.sum() == 90
    assert set(rows.ID) == {'SSHD-S-Aditya3', 'OtherAccount'}
    assert set(rows.AssignedDate) == {''}


def test_current_queue_cache_expires_and_force_refresh_removes_submissions():
    dm = manager()
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=[[task('a', 60)], [], []]) as fetch:
        assert dm.fetch_all_assigned_tasks_live()['Aditya']['backlog_dur'] == 60
        dm.fetch_all_assigned_tasks_live()
        assert fetch.call_count == 1
        dm._current_queue_cache['slice_assigned'] = (0, dm._current_queue_cache['slice_assigned'][1])
        assert dm.fetch_all_assigned_tasks_live() == {}
        assert dm.fetch_all_assigned_tasks_live(force_refresh=True) == {}
        assert fetch.call_count == 3


def test_cached_raw_queue_uses_current_mappings_and_exclusions():
    dm = manager()
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', return_value=[task('a', 60)]) as fetch:
        assert dm.fetch_all_assigned_tasks_live()['Aditya']['backlog_dur'] == 60
        dm._get_reporting_name = lambda uid, name: 'Riya'
        assert dm.fetch_all_assigned_tasks_live()['Riya']['backlog_dur'] == 60
        dm._get_reporting_name = lambda uid, name: 'Unassigned'
        assert dm.fetch_all_assigned_tasks_live() == {}
        assert fetch.call_count == 1


def test_cursor_pagination_deduplicates_and_ignores_submitted_tasks():
    with patch('slicing_dashboard.processing.current_queue.DailyWorkSource') as source:
        source.return_value.request.side_effect = [
            {'data': [task('a', 60)], 'meta': {'has_more': True, 'next_cursor': 'next'}},
            {'data': [task('a', 60), task('b', 90), task('submitted', 7200, status='slice_submitted')],
             'meta': {'has_more': False}},
        ]
        assert [r['id'] for r in fetch_queue(MagicMock(), 'slice_assigned')] == ['a', 'b']
        assert source.return_value.request.call_args_list[1].kwargs['params']['cursor'] == 'next'


def test_failed_refresh_cannot_restore_previous_assignment_capture():
    dm = manager()
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=[[task('a', 60)], ConnectionError(), []]) as fetch:
        assert dm.fetch_all_assigned_tasks_live()['Aditya']['backlog_dur'] == 60
        with pytest.raises(ConnectionError):
            dm.fetch_all_assigned_tasks_live(force_refresh=True)
        assert dm.fetch_all_assigned_tasks_live() == {}
        assert fetch.call_count == 3


@pytest.mark.parametrize('meta', [{'has_more': False, 'total_capped': True},
                                  {'has_more': True, 'next_cursor': 'same'}])
def test_incomplete_inventory_is_an_error(meta):
    with patch('slicing_dashboard.processing.current_queue.DailyWorkSource') as source:
        source.return_value.request.return_value = {'data': [task('a', 60)], 'meta': meta}
        with pytest.raises(ValueError):
            fetch_queue(MagicMock(), 'slice_assigned')


def test_partial_failure_preserves_successful_queue_with_visible_warning():
    dm = manager()
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=[ConnectionError(), [task('c', 90, status='slice_rework')]]):
        frame = dm.get_detailed_pending_assigned_df(overview_data={})
    figure = build_assigned_chart(frame[frame.Stage == 'Rework Assigned'], True)
    assert 'incomplete' in figure.layout.annotations[0].text
    assert figure.data[-1].customdata[0][4] == 'Unknown'


def test_assignment_date_and_age_return_without_using_historical_hours():
    dm = manager()
    dm._batches_master_cache['old']['batch_date'] = '2026-10-05'
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=[[task('a', 60)], []]), \
            patch('slicing_dashboard.management.periods.today_iso', return_value='2026-10-07'):
        frame = dm.get_detailed_pending_assigned_df(overview_data={})
    assigned = frame[frame.Stage == 'New Assigned']
    assert assigned.iloc[0].Duration == 60
    assert assigned.iloc[0].AssignedDate == '2026-10-05'
    assert assigned.iloc[0].DaysAssigned == 2
    assert assigned.iloc[0].AssignmentDateBasis == 'Account batch date'
    bar = build_assigned_chart(assigned, True).data[-1]
    assert bar.marker.color[0] == '#22c55e'
    assert '2026-10-05' in bar.customdata[0][4] and '2d ago' in bar.customdata[0][4]
    assert 'Assigned on: %{customdata[4]}' in bar.hovertemplate
    assert bar.customdata[0][6] == ''


def test_exact_batch_dates_keep_two_assignments_for_one_account_separate():
    dm = manager()
    dm._batches_master_cache = {batch: {'batch_id': batch, 'batch_date': day,
        'username': 'SSHD-S-Aditya3', 'status': 'batch_member_assigned', 'total_duration_seconds': 7200}
        for batch, day in [('one', '2026-10-04'), ('two', '2026-10-06')]}
    tasks = [{**task('a', 60), 'assignment_batch_id': 'one'},
             {**task('b', 120), 'assignment_batch_id': 'two'}]
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=[tasks, []]), \
            patch('slicing_dashboard.management.periods.today_iso', return_value='2026-10-07'):
        frame = dm.get_detailed_pending_assigned_df(overview_data={})
    rows = frame[frame.Stage == 'New Assigned']
    assert set(rows.AssignedDate) == {'2026-10-04', '2026-10-06'}
    assert set(rows.DaysAssigned) == {1, 3}
    assert rows.Duration.sum() == 180


def test_legacy_return_links_exact_rework_batch_and_ambiguous_dates_stay_unknown():
    batches = [{'batch_id': 'one', 'assignee_id': 1, 'status': 'batch_rework', 'batch_date': '2026-10-03'},
               {'batch_id': 'two', 'assignee_id': 1, 'status': 'batch_member_assigned', 'batch_date': '2026-10-06'}]
    row = {**task('a', 90, status='slice_rework'), 'slice_batch': 4}
    assert assignment_metadata(row, batches)['AssignedDate'] == ''
    linked = assignment_metadata(row, batches, [{'user_id': 1, 'legacy_batch_number': 4, 'batch_id': 'one'}])
    assert linked['AssignedDate'] == '2026-10-03' and linked['BatchID'] == 'one'
    assert linked['AssignmentDateBasis'] == 'Batch assignment date'
    direct = assignment_metadata({**row, 'assigned_at': '2026-10-07T01:00:00+08:00'}, batches)
    assert direct['AssignedDate'] == '2026-10-06'


def test_rework_color_uses_latest_matching_return_and_keeps_original_assignment():
    dm = manager()
    dm._batches_master_cache['old'].update(batch_date='2026-10-01', status='batch_rework')
    dm._batch_returns_cache = [
        {'batch_id': 'old', 'user_id': 1, 'legacy_batch_number': 4,
         'returned_at': '2026-10-11T12:00:00+08:00'},
        {'batch_id': 'old', 'user_id': 1, 'legacy_batch_number': 4,
         'returned_at': '2026-10-14T01:00:00+08:00'},
        {'batch_id': 'other', 'user_id': 1, 'legacy_batch_number': 5,
         'returned_at': '2026-10-14T12:00:00+08:00'},
    ]
    rework = {**task('r', 3600, status='slice_rework'), 'slice_batch': 4}
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=[[], [rework]]), \
            patch('slicing_dashboard.management.periods.today_iso', return_value='2026-10-14'):
        frame = dm.get_detailed_pending_assigned_df(overview_data={})
    row = frame[frame.Stage == 'Rework Assigned'].iloc[0]
    assert (row.AssignedDate, row.DaysAssigned) == ('2026-10-01', 13)
    assert (row.ReturnedDate, row.DaysReturned) == ('2026-10-13', 1)
    bar = build_assigned_chart(frame[frame.Stage == 'Rework Assigned'], True).data[-1]
    assert bar.marker.color[0] == '#fb7185'
    assert '2026-10-01' in bar.customdata[0][4]
    assert bar.customdata[0][6] == '<br>Returned on: 2026-10-13 · 1d ago'


def test_direct_return_dates_keep_same_account_segments_separate():
    dm = manager()
    rows = [{**task(str(index), 3600, status='slice_rework'),
             'assignment_batch_id': 'old', 'returned_at': returned}
            for index, returned in enumerate(['2026-10-08T12:00:00Z', '2026-10-14T12:00:00Z'])]
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=[[], rows]), \
            patch('slicing_dashboard.management.periods.today_iso', return_value='2026-10-14'):
        frame = dm.get_detailed_pending_assigned_df(overview_data={})
    rework = frame[frame.Stage == 'Rework Assigned']
    assert set(rework.ReturnedDate) == {'2026-10-08', '2026-10-14'}
    bars = [trace for trace in build_assigned_chart(rework, True).data if trace.type == 'bar']
    assert [trace.marker.color[0] for trace in bars] == ['#fda4af', '#991b1b']
    assert sum(sum(trace.x) for trace in bars) == 2


def test_unknown_return_never_uses_assignment_age_or_another_accounts_history():
    row = {**task('r', 90, status='slice_rework'), 'slice_batch': 4,
           'assigned_at': '2026-10-01T12:00:00Z'}
    metadata = assignment_metadata(row, [], [
        {'user_id': 2, 'legacy_batch_number': 4, 'returned_at': '2026-10-14T12:00:00Z'},
        {'user_id': 1, 'legacy_batch_number': 5, 'returned_at': '2026-10-14T12:00:00Z'},
    ])
    assert metadata['ReturnedDate'] == ''
    figure = build_assigned_chart(pd.DataFrame([{'User': 'Aditya', 'Stage': 'Rework Assigned',
        'Duration': 90, 'DaysAssigned': 13, **metadata}]), True)
    assert figure.data[-1].marker.color[0] == '#94a3b8'
    assert figure.data[-1].customdata[0][6] == '<br>Returned on: Unknown'


def test_newer_batch_return_overrides_old_task_timestamp_and_invalid_history_is_ignored():
    row = {**task('r', 90, status='slice_rework'), 'batch_id': 'one',
           'returned_at': '2026-10-10T12:00:00Z'}
    metadata = assignment_metadata(row, [], [
        {'batch_id': 'one', 'returned_at': 'invalid'},
        {'batch_id': 'one', 'returned_at': '2026-10-13T12:00:00Z'},
    ])
    assert metadata['ReturnedDate'] == '2026-10-13'


def test_ambiguous_legacy_return_batches_do_not_invent_a_return_date():
    row = {**task('r', 90, status='slice_rework'), 'slice_batch': 4}
    metadata = assignment_metadata(row, [], [
        {'user_id': 1, 'legacy_batch_number': 4, 'batch_id': batch, 'returned_at': returned}
        for batch, returned in [('one', '2026-10-13'), ('two', '2026-10-14')]
    ])
    assert metadata['ReturnedDate'] == ''


@pytest.mark.parametrize('age, color', [(0, '#fda4af'), (1, '#fb7185'), (2, '#f43f5e'),
                                     (3, '#dc2626'), (5, '#991b1b')])
def test_rework_return_color_bands(age, color):
    from datetime import date, timedelta
    returned = (date(2026, 10, 14) - timedelta(days=age)).isoformat()
    with patch('slicing_dashboard.plots.assigned_chart.today_iso', return_value='2026-10-14'):
        figure = build_assigned_chart(pd.DataFrame([{'User': 'Aditya', 'Stage': 'Rework Assigned',
            'Duration': 90, 'AssignedDate': '2026-09-01', 'ReturnedDate': returned}]), True)
    assert figure.data[-1].marker.color[0] == color

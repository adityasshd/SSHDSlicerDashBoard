"""Recover actual pending hours without changing task membership or identity."""
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from slicing_dashboard.processing.pending_review import fetch_items
from slicing_dashboard.processing.review_timing import recover_review_durations


def task(identifier='one', seconds=0, status='slice_pending_auditor_review', uid=7):
    return {'id': identifier, 'slicer_id': uid, 'slicer': 'account',
            'status': status, 'duration_seconds': seconds}


def timing(row=None, **changes):
    return {**(row or task()), 'start': 3, 'end': 102, **changes}


def page(rows, total=None, **meta):
    return {'items': rows, 'total': len(rows) if total is None else total,
            'meta': {'has_more': False, 'total_capped': False, **meta}}


def reader(payloads):
    source = MagicMock()
    source.request.side_effect = [{'id': 803}, *payloads]
    return source


def test_positive_queue_durations_need_no_extra_reads_or_mutation():
    rows = [task(seconds=99)]
    before = deepcopy(rows)
    with patch('slicing_dashboard.processing.review_timing.DailyWorkSource') as source:
        result = recover_review_durations(MagicMock(), rows)
    source.assert_not_called()
    assert rows == before
    assert result[0]['duration_seconds'] == 99
    assert result[0]['duration_source'] == '/api/slice/tasks'


def test_zero_and_missing_durations_recover_by_id_across_cursor_pages():
    rows = [task(), task('two', None, status='slice_pending_admin_review', uid=8)]
    before = deepcopy(rows)
    source = reader([page([timing(rows[0])], 2, has_more=True, next_cursor='next'),
                     page([timing(rows[1], start=12, end=72)], 2)])
    with patch('slicing_dashboard.processing.review_timing.DailyWorkSource', return_value=source):
        result = recover_review_durations(MagicMock(), rows)
    assert rows == before
    assert [r['duration_seconds'] for r in result] == [99, 60]
    assert [r['status'] for r in result] == [r['status'] for r in rows]
    bodies = [call.kwargs['body'] for call in source.request.call_args_list[1:]]
    assert bodies[0]['user_id'] == 803  # The authenticated actor, not either owner.
    assert bodies[0]['task_ids'] == ['one', 'two']
    assert bodies[1]['cursor'] == 'next' and bodies[1]['page'] == 2


def test_role_omission_uses_exact_task_detail_with_same_session():
    source = reader([page([]), timing()])
    with patch('slicing_dashboard.processing.review_timing.DailyWorkSource', return_value=source):
        result = recover_review_durations(MagicMock(), [task()])
    assert result[0]['duration_seconds'] == 99
    assert result[0]['duration_source'] == '/api/tasks/{task_id}'
    assert source.request.call_args.args == ('/api/tasks/one',)


@pytest.mark.parametrize('changes', [
    {'id': 'other'}, {'slicer_id': 8}, {'slicer_id': None},
    {'status': 'slice_completed'}, {'status': 'slice_pending_admin_review'},
    {'start': -1}, {'start': None}, {'start': False},
    {'end': float('nan')}, {'end': float('inf')}, {'end': 3}, {'end': 0},
])
def test_wrong_identity_changed_stage_or_invalid_timing_never_creates_hours(changes):
    # Missing-overview path exercises validation of direct detail IDs as well.
    source = reader([page([]), timing(**changes)])
    with patch('slicing_dashboard.processing.review_timing.DailyWorkSource', return_value=source):
        with pytest.raises(ValueError):
            recover_review_durations(MagicMock(), [task()])


@pytest.mark.parametrize('payloads', [
    [{}],
    [page([timing()], total=2)],
    [page([timing()], total_capped=True)],
    [page([timing(), timing()], total=1)],
    [page([timing(id='other')], total=1)],
    [page([timing()], 1, has_more=True, next_cursor='same'),
     page([], 1, has_more=True, next_cursor='same')],
    [page([], 1, has_more=True, next_cursor='next')],
    [page([timing()], 1, has_more=True, next_cursor='next'), page([], 0)],
])
def test_incomplete_capped_or_repeating_overview_is_not_a_complete_capture(payloads):
    source = reader(payloads)
    with patch('slicing_dashboard.processing.review_timing.DailyWorkSource', return_value=source):
        with pytest.raises(ValueError):
            recover_review_durations(MagicMock(), [task()])


@pytest.mark.parametrize('seconds', [-1, float('nan'), float('inf'), False])
def test_invalid_queue_values_are_not_reinterpreted_as_missing(seconds):
    with pytest.raises(ValueError):
        recover_review_durations(MagicMock(), [task(seconds=seconds)])


def test_recovered_rows_reach_the_correct_account_and_stage_totals():
    leader = task('leader', 120, 'slice_submitted')
    auditor = task()
    admin = task('admin', 0, 'slice_pending_admin_review', uid=8)
    source = reader([page([timing(auditor), timing(admin, start=0, end=60)])])
    evidence = []
    with patch('slicing_dashboard.processing.current_queue.fetch_queue', side_effect=[[leader], [auditor], [admin]]), \
         patch('slicing_dashboard.processing.review_timing.DailyWorkSource', return_value=source):
        accounts = fetch_items(MagicMock(is_authenticated=True), '2026-11-02', task_records=evidence)
    by_id = {row['user_id']: row for row in accounts}
    assert by_id[7]['leader_review_duration_seconds'] == 120
    assert by_id[7]['auditor_review_duration_seconds'] == 99
    assert by_id[8]['admin_review_duration_seconds'] == 60
    assert sum(row['leader_review_count'] + row['auditor_review_count'] + row['admin_review_count']
               for row in accounts) == 3
    assert len(evidence) == 3
    assert evidence[1]['queue_duration_seconds'] == 0
    assert evidence[1]['duration_start'] == 3

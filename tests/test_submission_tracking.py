from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from slicing_dashboard.processing.workflow_history import WorkflowStore
from slicing_dashboard.reporting.submission_tracking import (
    transition_plan, capture_submissions, saved_observed_submissions, tracking_instance,
)
from slicing_dashboard.plots.today_submissions_lollipop import build_today_submissions_lollipop

T0 = '2026-11-25T07:00:00+00:00'
T1 = '2026-11-25T07:01:00+00:00'
T2 = '2026-11-25T07:02:00+00:00'
T3 = '2026-11-25T07:03:00+00:00'


def task(status='slicing', uid=1, tid='one'):
    return {'id': tid, 'workflow_type': 'slice', 'slicer_id': uid,
            'slicer': 'account-one', 'duration_seconds': 120., 'status': status}


def manager():
    return SimpleNamespace(settings=SimpleNamespace(admin_username='leader', efficiency_leader_id=803),
                           scraper=SimpleNamespace(_base_url='https://source.example'),
                           _get_reporting_name=lambda uid, raw: 'Person',
                           db=SimpleNamespace(mongo_db=None, engine=None))


def test_baseline_stock_is_not_submissions_and_approvals_do_not_add_work():
    checkpoint, events = transition_plan(None, [task('slice_submitted')], T0, T1, 'scope')
    assert events == []
    _, events = transition_plan(checkpoint, [task('slice_completed')], T2, T3, 'scope')
    assert events == []


def test_transition_is_dated_by_two_observations_not_task_updated_time():
    checkpoint, _ = transition_plan(None, [task()], T0, T1, 'scope')
    incoming = {**task('slice_submitted'), 'updated_at': '1999-01-01T00:00:00'}
    _, events = transition_plan(checkpoint, [incoming], T2, T3, 'scope')
    assert len(events) == 1
    assert events[0]['display_date'] == '2026-11-25'
    assert events[0]['observed_after'] == T0
    assert events[0]['submission_timestamp'] is None


@pytest.mark.parametrize('prior,current', [
    (task(), task('slice_submitted', uid=2)),
    (task('slice_submitted'), task('slice_completed')),
])
def test_reassignment_and_approved_inventory_are_not_new_output(prior, current):
    checkpoint, _ = transition_plan(None, [prior], T0, T1, 'scope')
    assert transition_plan(checkpoint, [current], T2, T3, 'scope')[1] == []


def test_overnight_and_capture_crossing_midnight_remain_unknown():
    checkpoint, _ = transition_plan(None, [task()], '2026-11-24T18:00:00Z', '2026-11-24T18:01:00Z', 'scope')
    assert not transition_plan(checkpoint, [task('slice_submitted')], T2, T3, 'scope')[1]
    checkpoint, _ = transition_plan(None, [task()], T0, T1, 'scope')
    assert not transition_plan(checkpoint, [task('slice_submitted')],
                               '2026-11-25T18:29:59Z', '2026-11-25T18:30:01Z', 'scope')[1]


@pytest.mark.parametrize('rows', [[task(), task()], [{**task(), 'duration_seconds': float('nan')}],
                                  [{**task(), 'duration_seconds': None}]])
def test_invalid_or_duplicate_inventory_does_not_change_checkpoint(rows):
    checkpoint, _ = transition_plan(None, [task()], T0, T1, 'scope')
    original = deepcopy(checkpoint)
    with pytest.raises(ValueError):
        transition_plan(checkpoint, rows, T2, T3, 'scope')
    assert checkpoint == original


def test_events_survive_approval_restart_retry_and_rework_without_double_count(tmp_path):
    m = manager()
    store = WorkflowStore(path=tmp_path / 'tracking.sqlite3')
    instance = tracking_instance(m)
    checkpoint, _ = transition_plan(None, [task()], T0, T1, instance)
    checkpoint, events = transition_plan(checkpoint, [task('slice_submitted')], T2, T3, instance)
    store.save_many('submission-observation', events)
    store.save_many('submission-observation', events)  # retry after checkpoint failure
    store.save_many('submission-observation', [{**events[0], 'id': 'earlier-day',
                                               'display_date': '2026-11-24', 'duration_seconds': 9999}])
    store.save(checkpoint['id'], 'submission-tracking', checkpoint, replace=True)
    store = WorkflowStore(path=store.path)
    output = saved_observed_submissions(m, '2026-11-25', store=store)
    assert output['values']['submitted_total'] == 120
    assert output['users'][0]['submitted_count'] == 1
    fig = build_today_submissions_lollipop(output)
    assert fig.layout.meta['stock_not_daily_events'] is False
    assert fig.layout.meta['partial'] is True
    assert fig.layout.meta['submitted_tasks'] == 1
    assert fig.layout.title.text.startswith('Recorded submissions today')
    assert 'Tasks:' in fig.data[0].hovertemplate
    assert len(fig.data) == 1
    assert 'Recorded since' in fig.layout.annotations[0].text
    assert saved_observed_submissions(m, '2026-11-26', store=store)['available'] is False
    assert saved_observed_submissions(m, '2026-11-25', selected=[], store=store)['users'] == []


def test_capture_publishes_no_checkpoint_after_failed_inventory(tmp_path):
    m, store = manager(), WorkflowStore(path=tmp_path / 'tracking.sqlite3')
    with patch('slicing_dashboard.reporting.submission_tracking.fetch_inventory', side_effect=ValueError('partial')):
        with pytest.raises(ValueError):
            capture_submissions(m, store)
    assert store.get(tracking_instance(m) + ':checkpoint') is None
    assert store.records('submission-observation') == []

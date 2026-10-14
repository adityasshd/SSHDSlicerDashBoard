"""Same-cohort nesting, late reviews, returns, and combined rework stacks."""
import pandas as pd
import pytest

from slicing_dashboard.reporting.approval_funnel import cohort_records, prepare_funnel, STAGES
from slicing_dashboard.reporting.approval_reports import prepare_approval_trend
from slicing_dashboard.plots.approval_outcomes_chart import build_approval_outcomes_chart
from slicing_dashboard.processing.batch_ratios import batch_ratios
from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart
from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame


def batch(identifier, status, seconds=3600, member='Person', **extra):
    return dict(batch_id=identifier, batch_date='2026-10-06', status=status,
                total_duration_seconds=seconds, username=member,
                last_updated='2026-10-13T12:00:00+08:00', **extra)


def review(identifier, stage, action, at='2026-10-12T12:00:00+08:00', **extra):
    return dict(id=identifier + stage + action, batch_id=identifier, stage=stage,
                source='batch-review', active=True, action=action, event_at=at, **extra)


def test_one_cohort_has_nested_approvals_and_stage_outcomes_after_late_reviews():
    batches = [batch('admin', 'batch_completed', 7200),
               batch('auditor', 'batch_pending_admin_review', 3600),
               batch('leader', 'batch_pending_auditor_review', 1800),
               batch('returned', 'batch_rework', 900)]
    events = [review('returned', 'Auditor', 'Returned for Rework')]
    payload = cohort_records(events, batches, lambda b: b['username'], ['2026-10-06'])
    days, totals = prepare_funnel(payload, ['2026-10-06'])
    assert [days[0][stage.lower() + '_seconds'] for stage in STAGES] == [13500, 10800, 7200]
    assert totals['Auditor']['Rejected / returned']['seconds'] == 900
    assert totals['Admin']['Awaiting review']['seconds'] == 3600
    assert all(sum(value['count'] for value in stage.values()) == 4 for stage in totals.values())
    report = prepare_approval_trend({'history': [{'date': '2026-10-06', 'rows': [],
                                  'metadata': {'available': True}}]}, approvals={'funnel': payload})
    assert report['rows'][0]['admin_seconds'] == 7200
    for dark in (True, False):
        figure = build_approval_outcomes_chart(totals, dark)
        assert list(figure.data[0].y) == pytest.approx([3.75, 3, 2])
        assert figure.data[1].y[1] == .25
        assert figure.layout.xaxis.type == 'category'
        assert figure.layout.xaxis.title.text == 'Review stage'
        figure.to_json()


def test_reapproval_resets_return_outcome_without_multiplying_content():
    events = [review('one', 'Admin', 'Approved', '2026-10-07T10:00:00+08:00'),
              review('one', 'Admin', 'Returned for Rework', '2026-10-08T10:00:00+08:00'),
              review('one', 'Leader', 'Approved'), review('one', 'Leader', 'Approved')]
    old = batch('one', 'batch_completed')
    old['last_updated'] = '2026-10-07T09:00:00+08:00'
    payload = cohort_records(events, [old], lambda b: b['username'], ['2026-10-06'])
    days, totals = prepare_funnel(payload, ['2026-10-06'])
    assert list(payload['rows'][0]['outcomes']) == ['Approved', 'Awaiting review', 'Not reached']
    assert days[0]['leader_seconds'] == 3600 and days[0]['admin_seconds'] == 0
    assert totals['Admin']['Rejected / returned']['count'] == 0
    # Legacy local ledger timestamps are India time; reviews are Shanghai time.
    completed = batch('one', 'batch_completed')
    completed['last_updated'] = '2026-10-13 12:00:00'
    payload = cohort_records([review('one', 'Leader', 'Approved', '2026-10-13T13:00:00+08:00')],
                             [completed], lambda b: b['username'], ['2026-10-06'])
    assert payload['rows'][0]['outcomes'] == ['Approved'] * 3


def test_filters_unknown_duration_and_uncovered_dates_remain_honest():
    payload = cohort_records([], [batch('a', 'batch_completed'),
                                 batch('missing', 'batch_pending_admin_review', None, 'Other')],
                             lambda b: b['username'], ['2026-10-06'])
    days, totals = prepare_funnel(payload, ['2026-10-06', '2026-10-07'])
    assert all(days[0][stage.lower() + '_seconds'] is None for stage in STAGES)
    assert all(days[1][stage.lower() + '_seconds'] is None for stage in STAGES)
    filtered, _ = prepare_funnel(payload, ['2026-10-06'], ['Person'])
    assert all(filtered[0][stage.lower() + '_seconds'] == 3600 for stage in STAGES)
    figure = build_approval_outcomes_chart(totals)
    assert figure.data[0].y[0] is None and figure.data[0].customdata[0][2] == 1
    with pytest.raises(ValueError):
        cohort_records([], [batch('a', 'batch_completed')] * 2, lambda b: 'Person')


def test_returned_batch_without_rejection_stage_does_not_become_awaiting_or_approved():
    payload = cohort_records([review('one', 'Leader', 'Approved')],
                             [batch('one', 'batch_rework')], lambda b: b['username'], ['2026-10-06'])
    assert payload['rows'][0]['outcomes'] == ['Unknown'] * 3
    assert payload['rows'][0]['unresolved_return'] is True
    days, _ = prepare_funnel(payload, ['2026-10-06'])
    assert all(days[0][stage.lower() + '_seconds'] is None for stage in STAGES)


def test_rework_combines_same_person_and_preserves_saved_state_and_unique_returns():
    batches = [batch('done', 'batch_completed'), batch('waiting', 'batch_pending_admin_review')]
    event = dict(event_id='return', batch_id='waiting', returned_at='2026-10-05T12:00:00Z')
    frame = batch_ratios(batches, [event, event], '2026-10-01', '2026-10-13', lambda b: 'Person')
    assert frame['Completion State'].tolist() == ['Completed', 'Pending approvals']
    assert frame['Total Batches'].tolist() == [1, 1]
    restored = panel_frame({'data': frame_payload(frame, 'rework')})
    for dark in (True, False):
        figure = build_rework_ratio_chart(restored, '2026-10-01', dark)
        assert list(figure.data[0].x) == ['Person']
        assert list(figure.data[0].y) == [50]
        assert list(figure.data[1].y) == [50]
        assert figure.data[0].customdata[0][1] == 2
        assert figure.data[0].customdata[0][6] == '02:00:00'
        figure.to_json()
    # A person with no pending batches still has only one stack.
    figure = build_rework_ratio_chart(frame.iloc[:1], '2026-10-01', True)
    assert list(figure.data[0].x) == ['Person']
    assert list(figure.data[0].y) == [100]

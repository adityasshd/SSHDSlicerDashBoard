"""Exact-range completed hours must never be replaced with whole-batch hours."""
import pytest
import pandas as pd

from slicing_dashboard.plots.completed_hours_heatmap import (
    build_completed_hours_heatmap, completion_total)
from slicing_dashboard.plots.overview_charts import build_approval_progression
from slicing_dashboard.processing.batch_ratios import batch_ratios
from slicing_dashboard.reporting.approval_funnel import cohort_records
from slicing_dashboard.reporting.dashboard_panels import frame_payload
from tests.test_daily_report_page import application_namespace


COMPLETION = {
    'available': True, 'start': '2026-11-01', 'end': '2026-11-17',
    'rows': [
        {'User': 'A', 'seconds': 180000.0, 'tasks': 1110},
        {'User': 'B', 'seconds': 47009.866, 'tasks': 600},
    ]
}


def test_completed_heatmap_reconciles_to_exact_source_and_not_large_batch_cohort():
    figure = build_completed_hours_heatmap(COMPLETION, True)
    assert len(figure.data) == 1
    assert list(figure.data[0].x) == ['Completed<br>hours']
    assert len(figure.data[0].y) == 3  # two users and neutral Total
    assert list(figure.data[0].y) == ['A', 'B', '<b>Total</b>']
    assert figure.layout.meta['completed_seconds'] == pytest.approx(227009.866)
    assert figure.layout.meta['unattributed_tier_hours'] is True
    assert figure.layout.meta['column_totals'] == pytest.approx([227009.866/3600])
    assert '63:03' in figure.layout.annotations[-1].text
    assert figure.data[0].customdata[-1][0][1] == '63:03:30'
    assert 'Return tier attribution unavailable' in figure.layout.title.subtitle.text
    assert all(item[-1] is not None for row in figure.data[0].customdata[:-1] for item in row)
    assert figure.data[0].z[-1][0] == -1  # neutral Total uses same grid
    assert len(figure.layout.annotations) == 3


def test_completed_hours_user_filters_match_kpi_and_no_proration():
    figure = build_completed_hours_heatmap(COMPLETION, True, selected=['B'])
    assert figure.layout.meta['completed_seconds'] == pytest.approx(47009.866)
    assert list(figure.data[0].y) == ['B', '<b>Total</b>']
    assert completion_total(COMPLETION, ['B']) == pytest.approx(47009.866)
    assert completion_total(COMPLETION) == pytest.approx(227009.866)
    assert completion_total({'available': False, 'rows': [{'User':'A', 'seconds': 1000000}]}) is None
    assert not build_completed_hours_heatmap({'available': False, 'rows': []}).data
    assert not build_completed_hours_heatmap(COMPLETION, True, selected=[]).data


def test_pyramid_hours_are_verified_and_do_not_depend_on_batch_duration():
    # A batch with 150 original hours must not inflate 63 hours of completed video.
    batches = [dict(batch_id='old', batch_date='2026-11-04', username='A',
                    status='batch_completed', total_duration_seconds=540000)]
    cohort = cohort_records([], batches, lambda row: row['username'])
    figure = build_approval_progression(cohort, ['2026-11-04'], None, True,
                                        completion=COMPLETION, unit='Hours')
    assert figure.layout.meta['metric'] == 'source_date_completed_seconds'
    assert figure.layout.meta['verified_seconds'] == pytest.approx(227009.866)
    assert figure.data[0].x[0] == pytest.approx(227009.866 / 3600)
    assert figure.layout.meta['leader_hours'] is None
    assert figure.layout.meta['auditor_hours'] is None
    assert '63:03:30' in figure.layout.title.subtitle.text
    assert 'dated Admin approval event' in figure.data[0].hovertemplate
    assert '150' not in figure.to_json()
    limited = build_approval_progression(cohort, ['2026-11-04'], ['B'], True,
                                         completion=COMPLETION, unit='Hours')
    assert limited.layout.meta['verified_seconds'] == pytest.approx(47009.866)
    assert not build_approval_progression(cohort, ['2026-11-04'], None, True,
                                          completion=None, unit='Hours').data
    counts = build_approval_progression(cohort, ['2026-11-04'], None, True,
                                        completion=COMPLETION, unit='Batches')
    assert list(counts.data[0].x) == [1, 1, 1]
    assert counts.layout.meta['metric'] == 'distinct_batch_stage_count'
    assert 'Original cohort video duration' not in counts.data[0].hovertemplate


def test_rework_callback_switches_between_source_hours_and_original_batch_exposure():
    namespace, manager = application_namespace()
    handlers = namespace['app'].callback_map
    key = next(key for key in handlers if 'rework-ratio-chart.figure' in key and '@' not in key)
    callback = handlers[key]
    assert {'id': 'dashboard-saved-completion', 'property': 'data'} in callback['inputs']
    assert {'id': 'dashboard-live-completion', 'property': 'data'} in callback['inputs']
    fn = callback['callback'].__wrapped__
    cohort = batch_ratios([
        dict(batch_id='old', batch_date='2026-11-04', username='A', user='A',
             status='batch_completed', return_count=0, total_duration_seconds=540000)
    ], [], '2026-11-01', '2026-11-17', lambda row: row['user'])
    rework = {'request_id': 'test', 'available': True,
              'captured_at': '2026-11-17T07:00:00Z',
              'data': frame_payload(cohort, 'rework')}
    completed = {'request_id': 'test', 'available': True,
                 'captured_at': '2026-11-17T07:00:00Z',
                 'data': frame_payload(pd.DataFrame([
                     {'User': 'A', 'Completed Duration': 180000., 'Completed Tasks': 1110},
                     {'User': 'B', 'Completed Duration': 47009.866, 'Completed Tasks': 600},
                 ]), 'completion')}
    request = {'id': 'test', 'start': '2026-11-01', 'end': '2026-11-17'}
    verified, _, overview, _, _ = fn(
        request, rework, None, 0, 'Verified completed hours',
        completed, None, None, '/', None)
    assert verified.layout.meta['completed_seconds'] == pytest.approx(227009.866)
    assert '63:03:30' in str(overview)
    assert verified.layout.meta['column_totals'][0] * 3600 == pytest.approx(227009.866)
    exposure, _, _, _, _ = fn(request, rework, None, 0, 'Completed',
                                 completed, None, None, '/', None)
    assert exposure.layout.meta['column_totals'][0] == 1
    assert exposure.layout.meta['value_unit'] == 'mixed'
    assert exposure.layout.meta['verified_completed_seconds'] == pytest.approx(227009.866)
    assert exposure.layout.meta['column_totals'][-1] * 3600 == pytest.approx(227009.866)
    assert 'Duration' not in exposure.data[0].hovertemplate
    assert exposure.layout.title.subtitle.text is None
    # Missing or wrong-period completion must not substitute the 150-hour cohort.
    unavailable, _, _, _, _ = fn(request, rework, None, 0, 'Verified completed hours',
                                  {**completed, 'request_id': 'other'}, None, None, '/', None)
    assert not unavailable.data
    manager.get_batch_rework_ratio_df.assert_not_called()


def test_retired_pyramid_callback_cannot_reenter_dashboard_hours():
    namespace, _ = application_namespace()
    handlers = namespace['app'].callback_map
    assert 'approval-progression-chart.figure' not in handlers
    assert 'today-submissions-lollipop-chart.figure' in handlers
    assert 'kpi-approved-value.children' not in handlers or any(
        'dashboard-saved-completion' in str(callback.get('inputs'))
        for key, callback in handlers.items() if 'kpi-approved-value' in key)


def test_completed_tier_heatmap_uses_69_verified_hours_not_150_batch_hours():
    """Regression: source task completion must reconcile, even outside batch cohort."""
    namespace, manager = application_namespace()
    handlers = namespace['app'].callback_map
    callback = next(value for key, value in handlers.items()
                    if 'rework-ratio-chart.figure' in key and '@' not in key)
    paint = callback['callback'].__wrapped__

    batches = [dict(batch_id='legacy-batch', batch_date='2026-11-04',
                    username='A', user='A', status='batch_completed',
                    return_count=0, total_duration_seconds=150 * 3600)]
    batch_packet = {'request_id': 'p69', 'available': True,
                    'captured_at': '2026-11-18T06:00:00Z',
                    'data': frame_payload(batch_ratios(
                        batches, [], '2026-11-01', '2026-11-18',
                        lambda batch: batch['user']), 'rework')}
    hours_packet = {'request_id': 'p69', 'available': True,
                    'captured_at': '2026-11-18T06:00:00Z',
                    'data': frame_payload(pd.DataFrame([
                        {'User': 'A', 'Completed Duration': 36 * 3600, 'Completed Tasks': 1000},
                        {'User': 'B', 'Completed Duration': 33 * 3600, 'Completed Tasks': 900},
                    ]), 'completion')}
    request = {'id': 'p69', 'start': '2026-11-01', 'end': '2026-11-18'}

    figure, _, overview, _, _ = paint(
        request, batch_packet, None, 0, 'Completed',
        hours_packet, None, None, '/', None)
    assert list(figure.data[0].x) == [
        'No Rework', '1 Rework', '2 Reworks', '3+ Reworks', 'Unknown',
        'Completed<br>hours']
    assert list(figure.data[0].y) == ['A', 'B', '<b>Total</b>']
    assert figure.layout.meta['verified_completed_seconds'] == pytest.approx(69 * 3600)
    assert figure.layout.meta['column_totals'][-1] == pytest.approx(69)
    assert figure.layout.meta['tier_batch_totals'] == [1, 0, 0, 0, 0]
    assert figure.layout.meta['column_units'] == ['batches'] * 5 + ['hours']
    assert figure.layout.meta['return_tier_completed_hours_attributed'] is False
    assert figure.layout.meta['metric'] == 'completed_seconds_and_cohort_batch_counts'
    assert figure.layout.annotations[-1].text == '69:00'
    assert figure.data[0].customdata[-1][-1][6].startswith('69:00:00')
    assert '69:00:00' in str(overview)
    assert '150:00:00' not in figure.to_json()
    assert '150:00:00' not in str(overview)
    assert 'Original batch duration' not in figure.to_json()
    manager.get_batch_rework_ratio_df.assert_not_called()

    only_b, _, overview_b, _, _ = paint(
        request, batch_packet, ['B'], 0, 'Completed',
        hours_packet, None, None, '/', None)
    assert only_b.layout.meta['verified_completed_seconds'] == 33 * 3600
    assert only_b.layout.meta['column_totals'][-1] == 33
    assert list(only_b.data[0].y) == ['B', '<b>Total</b>']
    assert '33:00:00' in str(overview_b)


def test_completed_hours_still_render_when_batch_tier_capture_is_missing():
    namespace, _ = application_namespace()
    paint = next(value for key, value in namespace['app'].callback_map.items()
                 if 'rework-ratio-chart.figure' in key and '@' not in key)['callback'].__wrapped__
    request = {'id': 'no-batch', 'start': '2026-11-01', 'end': '2026-11-18'}
    hours = {'request_id': 'no-batch', 'available': True,
             'captured_at': '2026-11-18T06:00:00Z',
             'data': frame_payload(pd.DataFrame([
                 {'User': 'A', 'Completed Duration': 69 * 3600,
                  'Completed Tasks': 3000}
             ]), 'completion')}
    figure, _, overview, _, _ = paint(
        request, None, None, 0, 'Completed',
        hours, None, None, '/', None)
    assert figure.layout.meta['verified_total_seconds'] == pytest.approx(69 * 3600)
    assert figure.layout.meta['unknown_duration_seconds'] == pytest.approx(69 * 3600)
    assert figure.layout.meta['tier_duration_seconds'] == pytest.approx([0, 0, 0, 0, 69 * 3600])
    assert list(figure.data[0].x) == ['No Rework', '1 Rework', '2 Reworks',
                                    '3+ Reworks', 'Unknown', '<b>Total</b>']
    assert 'Completed paid video' in figure.layout.title.subtitle.text
    assert '69:00:00' in str(overview)


def test_completed_tiers_do_not_use_150_original_hours_when_efficiency_missing():
    from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart
    frame = batch_ratios([
        dict(batch_id='old', batch_date='2026-11-04', username='A',
             status='batch_completed', return_count=0,
             total_duration_seconds=150 * 3600)
    ], [], '2026-11-01', '2026-11-18', lambda row: row['username'])
    figure = build_rework_ratio_chart(
        frame, '2026-11-01', True,
        completion_state='Completed',
        completed_evidence={'available': False, 'rows': []})
    assert figure.layout.meta['verified_completed_seconds'] is None
    assert figure.layout.meta['column_totals'][-1] is None
    assert '150:00:00' not in figure.to_json()
    assert figure.layout.annotations[-1].text == '—'
    assert figure.layout.meta['tier_batch_totals'] == [1, 0, 0, 0, 0]


def test_pending_tier_counts_remain_separate_from_period_completed_hours():
    from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart
    frame = batch_ratios([
        dict(batch_id='review', batch_date='2026-11-04', username='A',
             status='batch_pending_admin_review', return_count=0,
             total_duration_seconds=150 * 3600)
    ], [], '2026-11-01', '2026-11-18', lambda row: row['username'])
    figure = build_rework_ratio_chart(
        frame, '2026-11-01', True, completion_state='Pending approvals',
        completed_evidence={'available': True, 'rows': [
            {'User': 'A', 'seconds': 69 * 3600, 'tasks': 3000}]})
    assert len(figure.data[0].x) == 5
    assert figure.layout.meta['tier_batch_totals'] == [1, 0, 0, 0, 0]
    assert figure.layout.meta['verified_completed_seconds'] is None
    assert '69:00:00' not in figure.to_json()

"""The new daily lollipop is submission evidence, not approval or labor hours."""
import pytest

from slicing_dashboard.reporting.daily_output import submitted_video_output
from slicing_dashboard.plots.today_submissions_lollipop import build_today_submissions_lollipop
from slicing_dashboard.pages.today_submissions import saved_today_submission_day
from tests.test_daily_report_page import application_namespace


DAY = {
    'date': '2026-11-17',
    'metadata': {'available': True, 'target_date': '2026-11-17',
                 'captured_at': '2026-11-17T16:00:00+05:30',
                 'reconciliation_pending': True},
    'rows': [
        {'User': 'A', 'Total Duration': 9000,
         'New Videos (First Time)': 7200, 'New Tasks': 3,
         'Old Rework': 3600, 'Old Rework Tasks': 1,
         'Same-day Rework': 1800, 'Same-day Rework Tasks': 1},
        {'User': 'B', 'Total Duration': 600,
         'New Videos (First Time)': 600, 'New Tasks': 1,
         'Old Rework': 0, 'Old Rework Tasks': 0,
         'Same-day Rework': 0, 'Same-day Rework Tasks': 0},
    ],
}


def test_total_includes_old_rework_legacy_total_did_not_include():
    output = submitted_video_output(DAY, expected_date='2026-11-17')
    assert output['available'] is True
    assert output['values'] == {
        'submitted_total': 13200,
        'new': 7800, 'old_rework': 3600, 'same_day_rework': 1800}
    assert output['counts'] == {
        'submitted_total': 6, 'new': 4, 'old_rework': 1, 'same_day_rework': 1}
    assert sum(output['values'][key] for key in
               ('new', 'old_rework', 'same_day_rework')) == output['values']['submitted_total']
    # Existing Daily Report's "Total Duration" is not used: 9,600 vs 13,200.
    assert sum(row['Total Duration'] for row in DAY['rows']) == 9600
    assert output['labor_seconds'] is None
    assert output['unit'] == 'submitted_video_seconds'


@pytest.mark.parametrize('dark', (True, False))
def test_lollipop_three_disjoint_buckets_and_a_nonadditive_total(dark):
    output = submitted_video_output(DAY, expected_date='2026-11-17')
    figure = build_today_submissions_lollipop(output, is_dark=dark)
    assert [item.name for item in figure.data] == [
        'Submitted today', 'New videos', 'Old rework', 'Same-day rework']
    assert len(figure.layout.shapes) == 4
    assert len(figure.data) == 4
    assert figure.layout.meta['metric'] == 'submitted_video_seconds'
    assert figure.layout.meta['component_seconds'] == output['values']
    assert figure.layout.meta['actual_labor_seconds'] is None
    assert figure.layout.meta['reconciled'] is True
    assert figure.data[0].x[0] == pytest.approx(13200 / 3600)
    assert '03:40:00' in str(figure.data[0].customdata)
    assert 'Video output, not time worked' in figure.layout.title.subtitle.text
    assert 'reconciliation pending' in figure.layout.title.subtitle.text
    figure.to_json()


def test_user_selection_and_empty_user_selection_never_inflate():
    a = submitted_video_output(DAY, ['A'], expected_date='2026-11-17')
    assert a['values']['submitted_total'] == 12600
    assert a['counts']['submitted_total'] == 5
    b = submitted_video_output(DAY, ['B'], expected_date='2026-11-17')
    assert b['values']['submitted_total'] == 600
    no_one = submitted_video_output(DAY, [], expected_date='2026-11-17')
    assert no_one['available'] is False
    assert 'No users selected' in no_one['reason']


def test_absent_or_wrong_day_capture_stays_unavailable_not_zero():
    for day in (None, {}, {**DAY, 'date': '2026-11-16'},
                {**DAY, 'metadata': {'available': False}},
                {**DAY, 'rows': [{'User':'A','New Videos (First Time)': 60}]}):
        output = submitted_video_output(day, expected_date='2026-11-17')
        assert output['available'] is False
        figure = build_today_submissions_lollipop(output)
        assert not figure.data
        assert 'substituted.' in figure.layout.annotations[0].text


def test_invalid_counts_and_inconsistent_source_rows_rejected():
    broken = {**DAY, 'rows': [
        {**DAY['rows'][0], 'Old Rework': -7},
        DAY['rows'][1]]}
    assert submitted_video_output(broken)['available'] is False
    duplicate = {**DAY, 'rows': [DAY['rows'][0], DAY['rows'][0]]}
    assert submitted_video_output(duplicate)['available'] is False
    invalid_count = {**DAY, 'rows': [
        {**DAY['rows'][0], 'New Tasks': 1.5}]}
    assert submitted_video_output(invalid_count)['available'] is False


def test_unknown_per_bucket_task_counts_do_not_invalidate_video_hours():
    partial = {**DAY, 'rows': [
        {**DAY['rows'][0], 'New Tasks': None}, DAY['rows'][1]]}
    output = submitted_video_output(partial, expected_date='2026-11-17')
    assert output['available'] is True
    assert output['values']['submitted_total'] == 13200
    assert output['counts']['new'] is None
    assert output['counts']['submitted_total'] is None


def test_existing_trend_daily_capture_reused_without_new_source_calls():
    from unittest.mock import Mock
    manager = Mock()
    trend = {'today': DAY}
    assert saved_today_submission_day(manager, trend, today='2026-11-17') == DAY
    manager.db.load_daily_chart_reports.assert_not_called()


def test_dashboard_has_new_plot_callback_and_no_old_pyramid_controls():
    namespace, _ = application_namespace()
    app = namespace['app']
    assert 'today-submissions-lollipop-chart.figure' in app.callback_map
    assert 'dashboard-today-submissions-evidence.data' in app.callback_map
    assert 'approval-progression-chart.figure' not in app.callback_map
    assert 'approval-progression-unit.value' not in app.callback_map
    render = app.callback_map['today-submissions-lollipop-chart.figure']
    assert {'id': 'selected-users-store', 'property': 'data'} in render['inputs']
    assert {'id': 'dashboard-today-submissions-evidence', 'property': 'data'} in render['inputs']

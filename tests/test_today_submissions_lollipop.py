"""Today's dashboard uses verified task counts, not fabricated video hours."""
import pytest

from slicing_dashboard.reporting.daily_output import (
    submitted_video_output, submission_rework_counts,
)
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


def test_submitted_and_rework_counts_are_distinct_with_subset_relationship():
    output = submission_rework_counts(DAY, expected_date='2026-11-17')
    assert output['available'] is True
    assert output['counts'] == {
        'submitted_total': 6, 'rework_total': 2,
        'new': 4, 'old_rework': 1, 'same_day_rework': 1}
    assert output['unit'] == 'task_submissions'
    assert output['counts']['submitted_total'] == (
        output['counts']['new'] + output['counts']['rework_total'])
    assert output['counts']['rework_total'] == (
        output['counts']['old_rework'] + output['counts']['same_day_rework'])


@pytest.mark.parametrize('dark', (True, False))
def test_lollipop_shows_only_two_counts_and_does_not_display_hours(dark):
    result = submission_rework_counts(DAY, expected_date='2026-11-17')
    figure = build_today_submissions_lollipop(result, is_dark=dark)
    assert [trace.name for trace in figure.data] == [
        'Submitted today', 'Rework submissions']
    assert len(figure.data) == len(figure.layout.shapes) == 2
    assert [trace.x[0] for trace in figure.data] == [6, 2]
    assert figure.layout.xaxis.title.text == 'Tasks submitted'
    assert figure.layout.meta['metric'] == 'dated_task_submission_count'
    assert figure.layout.meta['submitted_count'] == 6
    assert figure.layout.meta['rework_count'] == 2
    assert figure.layout.meta['rework_is_subset'] is True
    assert figure.layout.meta['video_hours_inferred'] is False
    assert 'must not be added' in figure.layout.title.subtitle.text
    assert 'reconciliation pending' in figure.layout.title.subtitle.text
    figure.to_json()


def test_user_filters_and_valid_zero_counts():
    a = submission_rework_counts(DAY, ['A'], expected_date='2026-11-17')
    assert a['counts']['submitted_total'] == 5
    assert a['counts']['rework_total'] == 2
    b = submission_rework_counts(DAY, ['B'], expected_date='2026-11-17')
    assert b['counts']['submitted_total'] == 1
    assert b['counts']['rework_total'] == 0
    no_one = submission_rework_counts(DAY, [], expected_date='2026-11-17')
    assert no_one['available'] is False
    assert 'No users selected' in no_one['reason']
    empty_day = {**DAY, 'rows': []}
    zeros = submission_rework_counts(empty_day, expected_date='2026-11-17')
    assert zeros['available'] is True
    assert zeros['counts']['submitted_total'] == 0
    assert zeros['counts']['rework_total'] == 0
    assert len(build_today_submissions_lollipop(zeros).data) == 2


def test_count_only_rows_do_not_require_unavailable_video_durations():
    count_rows = [
        {key: value for key, value in row.items()
         if key in ('User', 'New Tasks', 'Old Rework Tasks',
                    'Same-day Rework Tasks')}
        for row in DAY['rows']]
    result = submission_rework_counts({**DAY, 'rows': count_rows})
    assert result['available'] is True
    assert result['counts']['submitted_total'] == 6


def test_missing_and_invalid_dated_counts_are_unavailable_not_zero():
    invalid_rows = [
        {**DAY['rows'][0], 'Old Rework Tasks': None},
        {**DAY['rows'][1], 'New Tasks': 0.5},
    ]
    for day in (None, {}, {**DAY, 'date': '2026-11-16'},
                {**DAY, 'metadata': {'available': False}},
                {**DAY, 'rows': [{'User': 'A', 'New Tasks': 3}]},
                {**DAY, 'rows': invalid_rows},
                {**DAY, 'rows': [DAY['rows'][0], DAY['rows'][0]]}):
        result = submission_rework_counts(day, expected_date='2026-11-17')
        assert result['available'] is False
        figure = build_today_submissions_lollipop(result)
        assert not figure.data
        assert 'not substituted' in figure.layout.annotations[0].text


def test_old_duration_projection_is_not_used_for_the_count_only_plot():
    original = submitted_video_output(DAY, expected_date='2026-11-17')
    assert original['values']['submitted_total'] == 13200
    assert original['unit'] == 'submitted_video_seconds'
    assert original['labor_seconds'] is None


def test_saved_today_report_is_reused_without_new_source_calls():
    from unittest.mock import Mock
    manager = Mock()
    trend = {'today': DAY}
    assert saved_today_submission_day(manager, trend, today='2026-11-17') == DAY
    manager.db.load_daily_chart_reports.assert_not_called()


def test_dashboard_chart_wired_to_dated_evidence_and_user_filters():
    namespace, _ = application_namespace()
    callbacks = namespace['app'].callback_map
    assert 'today-submissions-lollipop-chart.figure' in callbacks
    assert 'dashboard-today-submissions-evidence.data' in callbacks
    assert 'approval-progression-chart.figure' not in callbacks
    render = callbacks['today-submissions-lollipop-chart.figure']
    assert {'id': 'selected-users-store', 'property': 'data'} in render['inputs']
    assert {'id': 'dashboard-today-submissions-evidence', 'property': 'data'} in render['inputs']

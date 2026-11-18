"""Submitted-video line and rework-lollipop regression coverage.

The plot displays video duration from a dated Daily submission report, not
the count-only interim chart, whole-batch duration or time spent working.
"""
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


def test_video_submission_projection_preserves_per_user_hours_and_rework_subset():
    output = submitted_video_output(DAY, expected_date='2026-11-17')
    assert output['available'] is True
    assert output['unit'] == 'submitted_video_seconds'
    assert output['values'] == {
        'submitted_total': 13200., 'new': 7800.,
        'old_rework': 3600., 'same_day_rework': 1800.,
    }
    assert output['counts']['submitted_total'] == 6
    assert output['users'] == [
        {'User': 'A', 'submitted_total': 12600,
         'new': 7200, 'old_rework': 3600, 'same_day_rework': 1800,
         'counts': {'new': 3, 'old_rework': 1, 'same_day_rework': 1}},
        {'User': 'B', 'submitted_total': 600,
         'new': 600, 'old_rework': 0, 'same_day_rework': 0,
         'counts': {'new': 1, 'old_rework': 0, 'same_day_rework': 0}},
    ]
    assert output['values']['submitted_total'] == sum(
        output['values'][key] for key in ('new', 'old_rework', 'same_day_rework'))
    # Legacy Total Duration excludes old rework. Never use it for this chart.
    assert sum(row['Total Duration'] for row in DAY['rows']) == 9600
    assert output['values']['submitted_total'] == 13200


@pytest.mark.parametrize('dark', (True, False))
def test_line_is_submitted_video_hours_and_lollipops_are_rework_hours(dark):
    output = submitted_video_output(DAY, expected_date='2026-11-17')
    figure = build_today_submissions_lollipop(output, is_dark=dark)
    assert [trace.name for trace in figure.data] == [
        'Submitted video', 'Old rework', 'Same-day rework',
    ]
    assert figure.data[0].mode == 'lines+markers+text'
    assert list(figure.data[0].y) == pytest.approx([3.5, 1/6])
    assert list(figure.data[1].y) == pytest.approx([1., 0.])
    assert list(figure.data[2].y) == pytest.approx([0.5, 0.])
    # Vertical stems are on each rework marker only when nonzero.
    stems = list(figure.layout.shapes)
    assert len(stems) == 2
    assert all(stem.type == 'line' and stem.y0 == 0 and stem.y1 > 0
               and stem.x0 == stem.x1 for stem in stems)
    assert figure.layout.meta['unit'] == 'video_hours'
    assert figure.layout.meta['metric'] == 'dated_submitted_video_duration'
    assert figure.layout.meta['submitted_seconds'] == pytest.approx(13200)
    assert figure.layout.meta['old_rework_seconds'] == pytest.approx(3600)
    assert figure.layout.meta['same_day_rework_seconds'] == pytest.approx(1800)
    assert figure.layout.meta['rework_is_subset'] is True
    assert figure.layout.meta['screen_time_included'] is False
    assert 'HH:MM' in figure.layout.yaxis.title.text
    assert 'included' in figure.layout.title.subtitle.text
    assert 'reconciliation pending' in figure.layout.title.subtitle.text
    figure.to_json()


def test_user_selection_recalculates_line_and_lollipops():
    a = submitted_video_output(DAY, ['A'], expected_date='2026-11-17')
    assert a['values']['submitted_total'] == 12600
    fig = build_today_submissions_lollipop(a)
    assert len(fig.data) == 3
    assert list(fig.data[0].y) == pytest.approx([3.5])
    assert fig.layout.meta['submitted_seconds'] == 12600
    b = submitted_video_output(DAY, ['B'], expected_date='2026-11-17')
    assert b['values']['submitted_total'] == 600
    fig_b = build_today_submissions_lollipop(b)
    assert list(fig_b.data[0].y) == pytest.approx([1/6])
    assert not fig_b.layout.shapes

    no_one = submitted_video_output(DAY, [], expected_date='2026-11-17')
    assert not no_one['available']
    assert 'No users selected' in no_one['reason']
    assert not build_today_submissions_lollipop(no_one).data


def test_valid_empty_capture_does_not_fabricate_any_hours():
    result = submitted_video_output({**DAY, 'rows': []}, expected_date='2026-11-17')
    assert result['available'] is True
    assert result['values']['submitted_total'] == 0
    assert not build_today_submissions_lollipop(result).data


def test_missing_and_invalid_dated_duration_unavailable_not_zero():
    invalid = {**DAY, 'rows': [{**DAY['rows'][0], 'Old Rework': None}]}
    broken = {**DAY, 'rows': [
        {**DAY['rows'][0], 'Same-day Rework': -20},
        DAY['rows'][1]]}
    for day in (
        None, {}, {**DAY, 'date': '2026-11-16'},
        {**DAY, 'metadata': {'available': False}},
        {**DAY, 'rows': [{'User': 'A', 'New Tasks': 3}]},
        invalid, broken,
        {**DAY, 'rows': [DAY['rows'][0], DAY['rows'][0]]},
    ):
        out = submitted_video_output(day, expected_date='2026-11-17')
        assert out['available'] is False
        plot = build_today_submissions_lollipop(out)
        assert not plot.data
        assert 'substituted.' in plot.layout.annotations[0].text


def test_count_only_source_is_not_falsely_presented_as_video_hours():
    count_rows = [
        {key: value for key, value in row.items()
         if key in ('User', 'New Tasks', 'Old Rework Tasks',
                    'Same-day Rework Tasks')}
        for row in DAY['rows']]
    counts = submission_rework_counts({**DAY, 'rows': count_rows})
    assert counts['available'] is True
    assert counts['counts']['submitted_total'] == 6
    duration = submitted_video_output({**DAY, 'rows': count_rows})
    assert duration['available'] is False
    figure = build_today_submissions_lollipop(counts)
    assert not figure.data


def test_chart_rejects_unreconciled_per_user_duration_not_fake_zero():
    output = submitted_video_output(DAY)
    output['users'][0]['old_rework'] = 999999.
    figure = build_today_submissions_lollipop(output)
    assert not figure.data
    assert 'unavailable' in figure.layout.annotations[0].text.lower()


def test_saved_today_report_reused_without_new_source_calls():
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

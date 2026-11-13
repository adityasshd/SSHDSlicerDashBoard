"""Queue composition and approval progression must keep their source scopes."""
import pandas as pd
import pytest

from slicing_dashboard.plots.overview_charts import build_review_workload_donut, build_approval_progression
from slicing_dashboard.plots.approval_trend_chart import build_approval_trend_chart
from slicing_dashboard.reporting.approval_funnel import cohort_records


@pytest.mark.parametrize('dark', [False, True])
def test_review_donut_sums_disjoint_stages_and_keeps_role_colors(dark):
    frame = pd.DataFrame([
        {'Stage': 'Pending Leader', 'Duration': 3600, 'Count': 2},
        {'Stage': 'Pending Leader', 'Duration': 1800, 'Count': 1},
        {'Stage': 'Pending Auditor', 'Duration': 900, 'Count': 1},
    ])
    figure = build_review_workload_donut(frame, dark)
    assert list(figure.data[0].values) == [5400, 900, 0]
    assert list(figure.data[0].marker.colors) == ['#F59E0B', '#8B5CF6', '#06B6D4']
    assert '01:45' in figure.layout.annotations[0].text
    assert figure.data[0].customdata[0][1] == 3


def test_approval_funnel_uses_one_filtered_cohort_and_nested_passes():
    batches = [dict(batch_id=str(index), batch_date='2026-10-06', username=user,
                    total_duration_seconds=3600, status=status, last_updated='2026-10-06T15:00:00')
               for index, (user, status) in enumerate([
                   ('A', 'batch_completed'), ('A', 'batch_pending_admin_review'),
                   ('A', 'batch_pending_auditor_review'), ('B', 'batch_completed')])]
    payload = cohort_records([], batches, lambda row: row['username'], ['2026-10-06'])
    figure = build_approval_progression(payload, ['2026-10-06'], ['A'], False)
    assert figure.data[0].type == 'funnel'
    assert list(figure.data[0].x) == [3, 2, 1]
    assert list(figure.data[0].y) == ['Leader', 'Auditor', 'Admin']
    empty = build_approval_progression(payload, ['2026-10-07'])
    assert not empty.data and empty.layout.annotations


def test_unknown_and_zero_sources_do_not_draw_invented_funnel_or_donut():
    assert not build_approval_progression(None, []).data
    frame = pd.DataFrame([{'Stage': 'Pending Leader', 'Duration': 0, 'Count': 0}])
    assert not build_review_workload_donut(frame).data


@pytest.mark.parametrize('dark', [False, True])
def test_sparse_primary_line_keeps_isolated_points_zero_and_visible_headroom(dark):
    report = {'rows': [{'date': '2026-10-01', 'total_seconds': 0},
                       {'date': '2026-10-02', 'total_seconds': None},
                       {'date': '2026-10-03', 'total_seconds': 3600}],
              'range_start': '2026-10-01', 'range_end': '2026-10-03'}
    figure = build_approval_trend_chart(report, dark, primary_only=True)
    assert list(figure.data[0].y) == [0, None, 1]
    assert figure.data[0].marker.size >= 7
    assert figure.data[0].cliponaxis is False and figure.data[0].connectgaps is False
    assert figure.layout.yaxis.range[-1] > 1 and figure.layout.height == 420
    assert figure.data[0].line.color == ('#c2fd75' if dark else '#165a50')


def test_completed_primary_uses_completion_evidence_without_substituting_submissions():
    report = {'rows': [{'date': '2026-11-01', 'total_seconds': 90000, 'completed_seconds': 3600},
                       {'date': '2026-11-02', 'total_seconds': 7200, 'completed_seconds': None}],
              'range_start': '2026-11-01', 'range_end': '2026-11-02'}
    figure = build_approval_trend_chart(report, False, primary_only=True, primary_metric='completed')
    assert list(figure.data[0].y) == [1, None]
    assert figure.data[0].name == 'Completed video'
    assert 'UTC+08' in figure.layout.xaxis.title.text

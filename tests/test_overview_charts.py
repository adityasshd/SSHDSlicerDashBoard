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
    assert list(figure.data[0].marker.colors) == (['#c2fd75', '#165a50', '#a78bfa'] if dark else ['#165a50', '#78b844', '#8b5cf6'])
    assert '01:45' in figure.layout.annotations[0].text
    assert figure.data[0].customdata[0][1] == 3


def test_progression_restores_nested_batch_counts_and_does_not_mix_completed_hours():
    batches = [
        dict(batch_id='a', batch_date='2026-11-01', username='A',
             status='batch_completed', total_duration_seconds=7200),
        dict(batch_id='b', batch_date='2026-11-02', username='A',
             status='batch_pending_admin_review', total_duration_seconds=3600),
        dict(batch_id='c', batch_date='2026-11-02', username='B',
             status='batch_pending_auditor_review', total_duration_seconds=1800),
    ]
    payload = cohort_records([], batches, lambda batch: batch['username'])
    # Period-completed task output has a different unit and must not replace
    # the Admin batch-count bar, even if it is much larger.
    completion = {'available': True, 'rows': [{'User': 'A', 'seconds': 227009.866, 'tasks': 1710}]}
    dates = ['2026-11-01', '2026-11-02']
    figure = build_approval_progression(payload, dates, None, True, completion)
    assert list(figure.data[0].x) == [3, 2, 1]
    assert list(figure.data[0].y) == ['Leader', 'Auditor', 'Admin']
    assert figure.layout.meta['metric'] == 'distinct_batch_stage_count'
    assert 'Not period-completed task hours' in figure.layout.title.subtitle.text
    assert list(build_approval_progression(payload, dates, ['A'], True, completion).data[0].x) == [2, 2, 1]
    assert not build_approval_progression(payload, dates, [], completion=completion).data


def test_out_of_range_cohort_cannot_invent_approval_history():
    payload = cohort_records([], [dict(batch_id='old', batch_date='2026-11-01', username='A',
        total_duration_seconds=546163, status='batch_completed')], lambda row: row['username'])
    assert not build_approval_progression(payload, ['2026-10-31']).data
    assert list(build_approval_progression(payload, ['2026-11-01']).data[0].x) == [1, 1, 1]


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

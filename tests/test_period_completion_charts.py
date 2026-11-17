"""Period completion must never inherit lifetime batches or migration dates."""
import pandas as pd
import pytest

from slicing_dashboard.plots.period_rework import build_period_rework
from slicing_dashboard.plots.overview_charts import build_approval_progression
from slicing_dashboard.processing.batch_ratios import batch_ratios
from slicing_dashboard.reporting.dashboard_panels import frame_payload
from tests.test_daily_report_page import application_namespace


def inventory():
    return batch_ratios([
        dict(batch_id='old', batch_date='2026-11-04', status='batch_completed',
             last_updated='2026-11-04T12:00:00', total_duration_seconds=546163, user='A'),
        dict(batch_id='pending', batch_date='2026-11-16', status='batch_pending_admin_review',
             total_duration_seconds=7200, user='B'),
    ], [], '2026-11-01', '2026-11-17', lambda batch: batch['user'])


COMPLETION = {'available': True, 'rows': [
    {'User': 'A', 'seconds': 30000, 'tasks': 200},
    {'User': 'B', 'seconds': 197009.87, 'tasks': 1510},
]}


@pytest.mark.parametrize('dark', [False, True])
def test_completed_keeps_tier_columns_without_inventing_period_attribution(dark):
    chart = build_period_rework(inventory(), COMPLETION, 'Completed', dark)
    assert len(chart.data) == 1
    assert list(chart.data[0].x)[:4] == [
        'No<br>Rework', '1<br>Rework', '2<br>Reworks', '3+<br>Reworks']
    assert all(row[column] is None for row in chart.data[0].z[:-1] for column in range(4))
    assert chart.layout.meta['column_totals'][-1] * 3600 == pytest.approx(227009.87)
    assert 'unavailable' in chart.layout.title.subtitle.text
    # Totals are a separate neutral trace and cannot affect the cell color scale.
    assert chart.layout.meta['column_maxima'][-1] == pytest.approx(197009.87 / 3600)
    assert chart.data[0].y[-1] == '<b>Total</b>'
    assert chart.data[0].colorscale[0][1] == chart.data[0].colorscale[1][1]
    assert not chart.data[0].showscale
    assert chart.layout.meta['single_aligned_matrix'] is True
    assert chart.layout.meta['color_scope'] == 'per_column'
    # The retired mixed-unit period view is not used by Dashboard heatmap
    # or pyramid. Exact period output stays in the completion chart.
    assert not build_approval_progression({}, ['2026-11-01', '2026-11-17'],
                                          completion=COMPLETION, is_dark=dark).data


def test_all_view_excludes_lifetime_completed_inventory_and_filters_people():
    chart = build_period_rework(inventory(), COMPLETION, 'All', True)
    assert list(chart.layout.meta['column_totals'][:4]) == [2, 0, 0, 0]
    assert chart.layout.meta['column_totals'][-1] * 3600 == pytest.approx(227009.87)
    selected = build_period_rework(inventory(), COMPLETION, 'Completed', True, ['A'])
    assert selected.layout.meta['column_totals'][-1] * 3600 == pytest.approx(30000)
    missing = build_period_rework(inventory(), {'available': False}, 'Completed', True)
    assert not missing.data


def test_retired_pyramid_cannot_inflate_today_submission_chart():
    from slicing_dashboard.reporting.daily_output import submitted_video_output
    from slicing_dashboard.plots.today_submissions_lollipop import build_today_submissions_lollipop
    namespace, _ = application_namespace()
    assert 'approval-progression-chart.figure' not in namespace['app'].callback_map
    # The retained batch ledger is not a dated task-submission report.
    chart = build_today_submissions_lollipop(
        submitted_video_output(None, expected_date='2026-11-17'))
    assert not chart.data
    assert 'No dated submission' in chart.layout.annotations[0].text

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
    assert list(chart.data[0].x)[:4] == ['No<br>Rework', '1<br>Rework', '2<br>Reworks', '3+<br>Reworks']
    assert all(list(row[:4]) == [None] * 4 for row in chart.data[0].z)
    assert chart.layout.meta['column_totals'][-1] * 3600 == pytest.approx(227009.87)
    assert 'unavailable' in chart.layout.title.subtitle.text
    # Totals are a separate neutral trace and cannot affect the cell color scale.
    assert chart.data[0].zmax == pytest.approx(197009.87 / 3600)
    assert list(chart.data[1].y) == ['<b>Total</b>']
    assert chart.data[1].colorscale[0][1] == chart.data[1].colorscale[1][1]
    assert not chart.data[0].showscale and not chart.data[1].showscale
    pyramid = build_approval_progression({}, ['2026-11-01', '2026-11-17'], completion=COMPLETION, is_dark=dark)
    assert pyramid.data[0].x[-1] * 3600 == pytest.approx(227009.87)
    assert pyramid.data[0].customdata[-1][0] == '63:03:30'
    assert pyramid.data[0].customdata[-1][1] == 'Batch count unavailable'


def test_all_view_excludes_lifetime_completed_inventory_and_filters_people():
    chart = build_period_rework(inventory(), COMPLETION, 'All', True)
    assert list(chart.layout.meta['column_totals'][:4]) == [2, 0, 0, 0]
    assert chart.layout.meta['column_totals'][-1] * 3600 == pytest.approx(227009.87)
    selected = build_period_rework(inventory(), COMPLETION, 'Completed', True, ['A'])
    assert selected.layout.meta['column_totals'][-1] * 3600 == pytest.approx(30000)
    missing = build_period_rework(inventory(), {'available': False}, 'Completed', True)
    assert not missing.data


def test_progression_rejects_a_completion_packet_from_another_period():
    namespace, _ = application_namespace()
    handler = namespace['app'].callback_map['approval-progression-chart.figure']['callback'].__wrapped__
    request = {'id': 'new', 'start': '2026-11-01', 'end': '2026-11-17'}
    packet = {'request_id': 'new', 'available': True, 'captured_at': 'test',
              'data': frame_payload(pd.DataFrame([
                  {'User': row['User'], 'Completed Duration': row['seconds'], 'Completed Tasks': row['tasks']}
                  for row in COMPLETION['rows']]), 'completion')}
    data = {'range_start': '2026-10-01', 'range_end': '2026-10-31',
            'history': [{'date': '2026-10-01'}]}
    assert not handler(data, None, 0, '/', request, packet, None, None).data
    data.update(range_start=request['start'], range_end=request['end'], history=[{'date': request['start']}])
    chart = handler(data, None, 0, '/', request, packet, None, None)
    assert chart.data[0].x[-1] * 3600 == pytest.approx(227009.87)

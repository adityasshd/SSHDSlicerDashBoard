"""Rework KPI hours use tier video durations, independent of weighted returns."""
import json

import dash
import pandas as pd
import pytest
from plotly.utils import PlotlyJSONEncoder

from slicing_dashboard.pages.dashboard_panels import render_rework_hours
from slicing_dashboard.plots.kpi_overview import build_kpi_layout
from slicing_dashboard.processing.batch_ratios import batch_ratios
from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame
from slicing_dashboard.reporting.rework_tiers import rework_hours
from tests.test_daily_report_page import application_namespace, components, payload_text


REQUEST = {'id': 'one'}


def tier_frame():
    batches = [dict(batch_id=str(index), username=f'account-{index}', batch_date='2026-10-01',
                    status='batch_completed' if index % 2 else 'batch_pending_admin_review',
                    total_duration_seconds=hours * 3600)
               for index, hours in enumerate([1, 2, 3, 4, 5, 6])]
    events = [dict(event_id=f'{index}-{attempt}', batch_id=str(index), returned_at='2026-10-02T03:00:00Z')
              for index, count in enumerate([0, 1, 2, 3, 4, 7]) for attempt in range(count)]
    return batch_ratios(batches, events + [events[-1]], '2026-10-01', '2026-10-07',
                        lambda batch: 'A' if int(batch['batch_id']) < 3 else 'B')


def packet():
    return {'available': True, 'request_id': 'one', 'captured_at': '2026-10-08T00:00:00Z',
            'data': frame_payload(tier_frame(), 'rework')}


def test_tier_hours_survive_capture_and_count_once_across_completion_states():
    hours = rework_hours(panel_frame(packet()))
    assert hours == {'No Rework': 1, '1 Rework': 2, '2 Reworks': 3, '3+ Reworks': 15}
    assert sum(hours.values()) == 21


def test_kpi_bar_uses_duration_shares_instead_of_batch_or_return_counts():
    content = render_rework_hours(REQUEST, None, packet(), None, 0)
    text = payload_text(content)
    assert '15:00:00' in text and '01:00:00' in text
    assert 'Returned batches: 20:00:00' in text
    bars = [node for node in components(content) if getattr(node, 'role', None) == 'progressbar']
    shares = [node.to_plotly_json()['props']['aria-valuenow'] for node in bars]
    assert shares == pytest.approx([100 / 21, 200 / 21, 300 / 21, 1500 / 21], abs=.01)


@pytest.mark.parametrize('selected,expected', [(['A'], ['01:00:00', '02:00:00', '03:00:00', '00:00:00']),
                                               (['B'], ['00:00:00', '15:00:00']), ([], ['00:00:00'])])
def test_user_filter_scopes_hours_before_aggregation(selected, expected):
    content = render_rework_hours(REQUEST, None, packet(), selected, 0)
    text = payload_text(content)
    assert all(value in text for value in expected)
    assert 'Breakdown unavailable' not in text


def test_legacy_upper_tiers_merge_hours_without_multiplying_returns():
    frame = pd.DataFrame([{'User': 'A', 'Total Batches': 4, 'No Rework': 1,
        '3 Reworks': 1, '4 Reworks': 1, '5+ Reworks': 1, '5+ Return Count': 8,
        'Tier Duration (hrs)': {'No Rework': 2, '3 Reworks': 4, '4 Reworks': 6, '5+ Reworks': 8}}])
    assert rework_hours(frame) == {'No Rework': 2, '1 Rework': 0, '2 Reworks': 0, '3+ Reworks': 18}


def test_old_capture_without_tier_hours_does_not_allocate_person_total():
    frame = pd.DataFrame([{'User': 'A', 'Total Batches': 1, 'No Rework': 1,
                           'Total Duration (hrs)': 100}])
    assert rework_hours(frame)['No Rework'] is None


def test_failed_refresh_retains_saved_hours_and_reports_saved_status():
    text = payload_text(render_rework_hours(REQUEST, packet(), {'request_id': 'one', 'available': False}, None, 0))
    assert '15:00:00' in text and 'Latest check failed' in text
    text = payload_text(render_rework_hours({'id': 'two'}, packet(), None, None, 0))
    assert '15:00:00' not in text and 'Loading latest data' in text


def test_invalid_capture_does_not_render_misleading_hours():
    invalid = packet()
    invalid['data']['records'][0]['Total Batches'] = 99
    text = payload_text(render_rework_hours(REQUEST, None, invalid, None, 0))
    assert 'Rework hours unavailable' in text and '15:00:00' not in text


def test_tier_durations_must_reconcile_with_the_saved_batch_total():
    invalid = packet()
    invalid['data']['records'][0]['Total Duration (hrs)'] += 1
    with pytest.raises(ValueError, match='Tier durations'):
        rework_hours(panel_frame(invalid))
    assert 'Rework hours unavailable' in payload_text(render_rework_hours(REQUEST, None, invalid, None, 0))


def test_reworked_total_is_unavailable_if_one_returned_tier_is_unknown():
    from slicing_dashboard.plots.kpi_overview import build_rework_hours_metric
    content = build_rework_hours_metric({'No Rework': 90, '1 Rework': 2, '2 Reworks': None, '3+ Reworks': 4})
    assert any(getattr(node, 'children', None) == 'Returned batches: —' for node in components(content))
    assert 'Breakdown unavailable' in payload_text(content)


def test_metric_repaints_after_summary_replacement_without_new_source_reads():
    namespace, manager = application_namespace()
    callback = namespace['app'].callback_map['kpi-rework-breakdown.children']
    paint = callback['callback'].__wrapped__
    layout = json.loads(json.dumps(build_kpi_layout({}, {}, True), cls=PlotlyJSONEncoder))
    text = payload_text(paint(layout, REQUEST, packet(), None, ['B'], 0, '/'))
    assert '15:00:00' in text
    assert {'id': 'kpi-cards', 'property': 'children'} in callback['inputs']
    manager.get_batch_rework_ratio_df.assert_not_called()
    manager.fetch_dashboard_data.assert_not_called()
    for absent in (None, [], {'type': 'Alert', 'props': {}}, [{'type': 'Alert', 'props': {}}]):
        with pytest.raises(dash.exceptions.PreventUpdate):
            paint(absent, REQUEST, packet(), None, None, 0, '/')

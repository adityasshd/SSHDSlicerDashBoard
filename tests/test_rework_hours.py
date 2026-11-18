"""Overview shows return-tier batch counts; original hours remain audit-only."""
import pandas as pd
import pytest

from slicing_dashboard.pages.dashboard_panels import render_rework_hours
from slicing_dashboard.plots.kpi_overview import build_rework_count_metric
from slicing_dashboard.processing.batch_ratios import batch_ratios
from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame
from slicing_dashboard.reporting.rework_tiers import rework_hours, rework_counts
from tests.test_daily_report_page import application_namespace, components, payload_text

REQUEST = {'id': 'one'}


def tier_frame():
    batches = [
        dict(batch_id=str(index), username=f'account-{index}',
             batch_date='2026-10-01',
             status='batch_completed' if index % 2 else 'batch_pending_admin_review',
             total_duration_seconds=hours * 3600,
             return_count=[0, 1, 2, 3, 4, 7][index])
        for index, hours in enumerate([1, 2, 3, 4, 5, 6])
    ]
    events = [
        dict(event_id=f'{index}-{attempt}', batch_id=str(index),
             returned_at='2026-10-02T03:00:00Z')
        for index, count in enumerate([0, 1, 2, 3, 4, 7])
        for attempt in range(count)
    ]
    return batch_ratios(
        batches, events + [events[-1]], '2026-10-01', '2026-10-07',
        lambda batch: 'A' if int(batch['batch_id']) < 3 else 'B')


def packet():
    return {'available': True, 'request_id': 'one',
            'captured_at': '2026-10-08T00:00:00Z',
            'data': frame_payload(tier_frame(), 'rework')}


def test_old_original_duration_is_retained_for_audit_but_not_ui():
    frame = panel_frame(packet())
    assert rework_hours(frame) == {
        'No Rework': 1, '1 Rework': 2, '2 Reworks': 3,
        '3+ Reworks': 15, 'Unknown': 0}
    assert rework_counts(frame) == {
        'No Rework': 1, '1 Rework': 1, '2 Reworks': 1,
        '3+ Reworks': 3, 'Unknown': 0}
    content = payload_text(render_rework_hours(REQUEST, None, packet(), None, 0))
    assert 'Rework batches' in content and 'Returned: 5' in content
    assert '15:00:00' not in content and 'Original video duration' not in content


def test_overview_distribution_uses_batch_shares_not_duration_shares():
    content = render_rework_hours(REQUEST, None, packet(), None, 0)
    bars = [node for node in components(content) if getattr(node, 'role', None) == 'progressbar']
    shares = [node.to_plotly_json()['props']['aria-valuenow'] for node in bars]
    assert shares == pytest.approx([100 / 6, 100 / 6, 100 / 6, 300 / 6], abs=.01)
    assert all('batches' not in str(node.to_plotly_json()).lower() or
               'hours' not in str(node.to_plotly_json()).lower() for node in bars)


@pytest.mark.parametrize('selected,returned', [(['A'], 2), (['B'], 3), ([], 0)])
def test_user_filter_scopes_batch_counts(selected, returned):
    content = payload_text(render_rework_hours(REQUEST, None, packet(), selected, 0))
    assert f'Returned: {returned}' in content
    assert 'HH:MM:SS' not in content
    assert 'Breakdown unavailable' not in content


def test_completion_and_pending_modes_show_disjoint_batch_counts():
    completed = payload_text(render_rework_hours(
        REQUEST, None, packet(), None, 0, completion_state='Completed'))
    pending = payload_text(render_rework_hours(
        REQUEST, None, packet(), None, 0, completion_state='Pending approvals'))
    assert 'Returned: 3' in completed
    assert 'Returned: 2' in pending
    assert 'Original batch duration' not in completed + pending
    assert 'Latest saved batch status' not in completed + pending


def test_invalid_tier_totals_do_not_render_credible_counts():
    invalid = packet()
    invalid['data']['records'][1]['Total Batches'] = 99
    content = render_rework_hours(REQUEST, None, invalid, None, 0)
    assert 'Batch counts unavailable' in payload_text(content)
    assert any(node.children == 'Returned: —' for node in components(content))


def test_modified_unrelated_duration_does_not_change_count_only_ui():
    changed = packet()
    changed['data']['records'][1]['Total Duration (hrs)'] += 1000
    with pytest.raises(ValueError, match='Tier durations'):
        rework_hours(panel_frame(changed))
    # Rework counts intentionally do not use original batch duration.
    assert rework_counts(panel_frame(changed)) == rework_counts(panel_frame(packet()))
    assert 'Returned: 5' in payload_text(render_rework_hours(REQUEST, None, changed, None, 0))


def test_missing_count_is_unavailable_not_estimated_from_duration():
    content = build_rework_count_metric({
        'No Rework': 90, '1 Rework': 2, '2 Reworks': None,
        '3+ Reworks': 4, 'Unknown': 1})
    assert any(node.children == 'Returned: —' for node in components(content))
    assert 'Breakdown unavailable' in payload_text(content)


def test_legacy_tiers_keep_exact_batch_counts():
    frame = pd.DataFrame([{'User': 'A', 'Total Batches': 4, 'No Rework': 1,
        '3 Reworks': 1, '4 Reworks': 1, '5+ Reworks': 1, '5+ Return Count': 8,
        'Tier Duration (hrs)': {
            'No Rework': 2, '3 Reworks': 4, '4 Reworks': 6, '5+ Reworks': 8}}])
    assert rework_counts(frame) == {'No Rework': 1, '1 Rework': 0,
        '2 Reworks': 0, '3+ Reworks': 3, 'Unknown': 0}


def test_failed_refresh_keeps_saved_batch_count_with_status():
    text = payload_text(render_rework_hours(
        REQUEST, packet(), {'request_id': 'one', 'available': False}, None, 0))
    assert 'Returned: 5' in text and 'Latest read failed' in text
    text = payload_text(render_rework_hours({'id': 'two'}, packet(), None, None, 0))
    assert 'Returned: 5' not in text and 'Loading latest data' in text


def test_callback_updates_overview_without_extra_source_reads():
    namespace, manager = application_namespace()
    callbacks = namespace['app'].callback_map
    callback = next(value for key, value in callbacks.items()
                    if 'dashboard-ready-rework.data' in key)
    paint = callback['callback'].__wrapped__
    request = {**REQUEST, 'start': '2026-10-01', 'end': '2026-10-07'}
    _, _, content, _, _ = paint(
        request, packet(), None, 0, 'All', None, None, None, '/', None)
    assert 'Returned: 5' in payload_text(content)
    assert not any(item['id'] == 'kpi-cards' for item in callback['inputs'])
    manager.get_batch_rework_ratio_df.assert_not_called()
    manager.fetch_dashboard_data.assert_not_called()

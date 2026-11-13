"""Return feedback counts are events, while each event can mention many reasons."""
from unittest.mock import patch

from slicing_dashboard.data_manager import DataManager
from slicing_dashboard.plots.return_reasons_chart import build_return_reasons_chart, classify_return_reason


def event(identity, user='one', reason='Missing action', stamp='2026-10-05T12:00:00Z', **extra):
    return {'event_id': identity, 'username': user, 'returned_at': stamp, 'reason': reason, **extra}


def test_mentions_use_return_event_denominator_and_deduplicate_events():
    first = event('a', reason='Multiple actions and missing action')
    figure = build_return_reasons_chart([
        first, first, event('b', reason='Missing action'), event('c', user='two', reason=''),
    ], canonical_map={'one': 'Riya', 'two': 'Priya'})
    missing = next(trace for trace in figure.data if trace.name == 'Missing Action')
    combined = next(trace for trace in figure.data if trace.name == 'Combined Actions')
    assert list(missing.y) == ['Riya', 'Priya']
    assert list(missing.x) == [2, 0]
    assert list(missing.customdata[0]) == [100, 2]
    assert list(combined.customdata[0]) == [50, 2]
    assert sum(sum(trace.x) for trace in figure.data) == 4
    assert '3 returns' in figure.layout.annotations[0].text
    assert '4 reason mentions' in figure.layout.annotations[0].text
    assert 'No reviewer note' in {trace.name for trace in figure.data}
    assert figure.layout.yaxis.autorange == 'reversed'
    figure.to_json()


def test_india_date_boundary_unknown_dates_and_current_id_mapping():
    rows = [event('previous', stamp='2026-10-05T01:00:00+08:00'),
            event('included', stamp='2026-10-06T01:00:00+08:00', user_id=12, canonical_user='Old'),
            event('unknown', stamp=None), event('next', stamp='2026-10-06T12:00:00Z')]
    figure = build_return_reasons_chart(rows, start='2026-10-05', end='2026-10-05',
        canonical_map={'12': 'Riya'}, selected_users=['Riya'])
    assert list(figure.data[0].y) == ['Riya']
    assert list(figure.data[0].x) == [1]
    empty = build_return_reasons_chart(rows, selected_users=['Nobody'])
    assert not empty.data and 'No batch return feedback' in empty.layout.annotations[0].text


def test_general_pick_word_does_not_imply_combined_actions():
    assert classify_return_reason('Pick the correct guidelines.') == ['Guidelines / Other']
    assert classify_return_reason('Combine these actions; unnecessarily split.') == ['Over-Segmentation']


def test_viewer_refresh_reads_saved_returns_without_contacting_upstream(monkeypatch):
    monkeypatch.setenv('DASHBOARD_ROLE', 'viewer')
    manager = DataManager.__new__(DataManager)
    manager._batch_returns_cache = [event('saved')]
    with patch.object(manager, 'sync_batch_returns') as sync:
        assert manager.get_batch_returns_records(force_refresh=True) == manager._batch_returns_cache
        sync.assert_not_called()

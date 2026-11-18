"""Return history counts observations once, independent of reviewer identity."""
import pytest

from slicing_dashboard.data_manager import DataManager
from slicing_dashboard.processing.batch_return_history import reconcile_batch_returns
from slicing_dashboard.processing.batch_ratios import batch_ratios


def batch(identifier, count=0, **kwargs):
    return {
        'batch_id': identifier, 'batch_date': '2026-11-17',
        'username': 'One', 'canonical_user': 'One',
        'status': 'batch_completed', 'total_duration_seconds': 3600,
        'return_count': count, **kwargs,
    }


def event(batch_id, stamp, viewer=1, identifier=None):
    return {'batch_id': batch_id, 'returned_at': stamp,
            'user_id': viewer,
            'event_id': identifier or f'{viewer}_{batch_id}_{stamp}'}


def test_cross_viewer_duplicate_does_not_inflate_batch_rework():
    a = event('B1', '2026-11-17T08:00:00+05:30', 10)
    b = event('B1', '2026-11-17T02:30:00Z', 20)  # same instant, another viewer
    c = event('B1', '2026-11-17T09:00:00+05:30', 10)  # actual second return
    report = reconcile_batch_returns([batch('B1', count=2)], [a, b, a, c])
    row = report['records'][0]
    assert row['observed_return_count'] == 2
    assert row['observed_return_dates'] == 1
    assert row['first_observed_return'] == '2026-11-17T08:00:00+05:30'
    assert row['last_observed_return'] == '2026-11-17T09:00:00+05:30'
    assert row['ledger_discrepancy'] == 0
    assert report['summary']['distinct_observed_returns'] == 2
    assert report['summary']['duplicate_event_documents'] == 2
    assert report['summary']['batches_with_multiple_returns'] == 1
    assert report['complete_lifetime_history'] is False
    assert report['coverage'] == 'observed_events_only'


def test_date_cutoff_uses_ist_and_does_not_compare_current_ledger_as_of_history():
    events = [
        event('B1', '2026-11-17T18:20:00Z'),
        event('B1', '2026-11-17T18:40:00Z'),  # IST Nov 18
    ]
    report = reconcile_batch_returns([batch('B1', count=2)], events,
                                     through_date='2026-11-17')
    assert report['records'][0]['observed_return_count'] == 1
    assert report['records'][0]['ledger_discrepancy'] is None
    assert report['summary']['after_cutoff_documents'] == 1
    assert report['summary']['ledger_mismatch_batches'] is None


def test_missing_batch_and_bad_event_are_not_silently_discarded():
    report = reconcile_batch_returns(
        [batch('Known'), batch('No observed history')],
        [event('Orphan', '2026-11-17T08:00:00+05:30'),
         {'batch_id': 'Known', 'returned_at': None},
         {'batch_id': 'Known', 'returned_at': 'invalid timestamp'},
         {'returned_at': '2026-11-17T08:00:00Z'}])
    assert report['summary']['unlinked_batch_count'] == 1
    assert report['summary']['unlinked_event_count'] == 1
    assert report['summary']['unusable_event_documents'] == 3
    assert report['summary']['batch_ledger_count'] == 2
    assert report['summary']['batches_with_observed_returns'] == 1
    assert next(row for row in report['records'] if row['batch_id'] == 'No observed history')['observed_return_count'] == 0
    assert next(row for row in report['records'] if row['batch_id'] == 'Orphan')['ledger_match'] is False
    assert all('reviewer' not in row and 'returned_by' not in row
               for row in report['records'])


def test_ledger_difference_detected_but_not_silently_overwritten():
    report = reconcile_batch_returns([batch('Known', count=4)],
                                     [event('Known','2026-11-17T08:00:00Z')])
    row = report['records'][0]
    assert row['observed_return_count'] == 1
    assert row['ledger_return_count'] == 4
    assert row['ledger_discrepancy'] == -3
    assert report['summary']['ledger_mismatch_batches'] == 1


def test_duplicate_batch_id_refused_to_avoid_ambiguous_status():
    with pytest.raises(ValueError, match='Duplicate batch'):
        reconcile_batch_returns([batch('A'), batch('A')], [])


def test_rework_tiers_use_batch_return_occurrences_not_synthetic_user_ids():
    batches = [batch('B1', count=1), batch('B2', count=2)]
    events = [
        event('B1','2026-11-17T08:00:00Z', 10),
        event('B1','2026-11-17T08:00:00Z', 20),
        event('B2','2026-11-17T08:00:00Z', 10),
        event('B2','2026-11-17T09:00:00Z', 10),
    ]
    frame = batch_ratios(batches, events, '2026-11-17', '2026-11-17',
                         lambda row: row['canonical_user'])
    assert len(frame) == 1
    assert frame.iloc[0]['Total Batches'] == 2
    assert frame.iloc[0]['1 Rework'] == 1
    assert frame.iloc[0]['2 Reworks'] == 1
    assert frame.iloc[0]['No Rework'] == 0
    assert frame.iloc[0]['Total Duration (hrs)'] == 2


def test_manager_readonly_report_preserves_existing_cache_and_staleness():
    manager = DataManager.__new__(DataManager)
    manager._batches_master_cache = {'B1': batch('B1', count=1)}
    manager._batch_returns_cache = [event('B1','2026-11-17T08:00:00Z')]
    manager._returns_source_error = None
    snapshot = list(manager._batch_returns_cache)
    result = manager.get_batch_return_history_report()
    assert result['source_fresh'] is True
    assert result['records'][0]['observed_return_count'] == 1
    assert result['summary']['ledger_mismatch_batches'] == 0
    assert manager._batch_returns_cache == snapshot
    manager._returns_source_error = 'Return history unavailable'
    failed = manager.get_batch_return_history_report()
    assert failed['source_fresh'] is False
    assert failed['source_error'] == 'ReturnHistorySourceIncomplete'
    assert failed['records'][0]['observed_return_count'] == 1
    assert failed['complete_lifetime_history'] is False


def test_genuine_distinct_return_ids_at_same_timestamp_are_not_collapsed():
    # A real source ID takes precedence if timestamp resolution is coarse.
    one = event('B1', '2026-11-17T08:00:00Z', viewer=1, identifier='return-first')
    two = event('B1', '2026-11-17T08:00:00Z', viewer=1, identifier='return-second')
    report = reconcile_batch_returns([batch('B1', count=2)], [one, two])
    assert report['summary']['distinct_observed_returns'] == 2
    assert report['records'][0]['ledger_discrepancy'] == 0
    ratios = batch_ratios([batch('B1', count=2)], [one, two],
                          '2026-11-17', '2026-11-17',
                          lambda row: row['canonical_user'])
    assert ratios.iloc[0]['2 Reworks'] == 1


def test_unverified_return_tier_goes_to_unknown_and_preserves_batch_hours():
    from slicing_dashboard.reporting.rework_tiers import rework_hours
    from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart
    from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame

    batches = [
        batch('Verified-zero', count=0),
        batch('Verified-one', count=1),
        batch('Unobserved', count=3),  # feed omitted the ledger's returns
        batch('Bad-timestamp', count=0),
    ]
    returns = [
        event('Verified-one', '2026-11-17T08:00:00Z'),
        {'batch_id': 'Bad-timestamp', 'returned_at': 'not a time'},
    ]
    frame = batch_ratios(batches, returns, '2026-11-17', '2026-11-17',
                         lambda row: row['canonical_user'])
    row = frame.iloc[0]
    assert row['Total Batches'] == 4
    assert row['No Rework'] == 1
    assert row['1 Rework'] == 1
    assert row['Unknown'] == 2
    assert row['Tier Duration (hrs)']['Unknown'] == pytest.approx(2)
    assert sum(row['Tier Duration (hrs)'].values()) == pytest.approx(
        row['Total Duration (hrs)'])
    totals = rework_hours(frame)
    assert totals['Unknown'] == pytest.approx(2)
    fig = build_rework_ratio_chart(panel_frame({'data': frame_payload(frame, 'rework')}),
                                   '2026-11-17', True)
    assert list(fig.data[0].x)[-1] == 'Unknown'
    assert fig.layout.meta['column_totals'][-1] == pytest.approx(2)
    assert sum(fig.layout.meta['column_totals']) == pytest.approx(4)
    assert 'incomplete batch return histories' in fig.layout.title.subtitle.text


def test_missing_ledger_return_count_is_unknown_but_future_verified_returns_are_not():
    a = batch('Missing-ledger')
    a.pop('return_count')
    future = batch('Future-verified', count=2)
    returns = [
        event('Future-verified', '2026-11-17T08:00:00Z'),
        event('Future-verified', '2026-11-19T08:00:00Z'),
    ]
    frame = batch_ratios([a, future], returns, '2026-11-17', '2026-11-17',
                         lambda row: row['canonical_user'])
    row = frame.iloc[0]
    assert row['Unknown'] == 1
    assert row['1 Rework'] == 1
    assert row['No Rework'] == 0
    assert row['2 Reworks'] == 0
    assert row['Total Batches'] == 2


def test_ledger_event_overcount_is_unknown_not_falsely_three_plus():
    b = batch('Mismatch', count=1)
    returns = [event('Mismatch', '2026-11-17T08:00:00Z'),
               event('Mismatch', '2026-11-17T09:00:00Z')]
    row = batch_ratios([b], returns, '2026-11-17', '2026-11-17',
                       lambda entry: entry['canonical_user']).iloc[0]
    assert row['Unknown'] == 1
    assert row['2 Reworks'] == 0
    assert row['3+ Reworks'] == 0

"""Evidence-first per-batch return history.

A batch-return-history API response can contain at most 100 recent records
per permitted operator and does not advertise pagination. Consequently
this analysis counts *observed* return events, not assured lifetime returns.
Reviewer identity is deliberately neither required nor inferred.
"""
from collections import defaultdict
from datetime import date

from slicing_dashboard.processing.daily_work import instant


def reconcile_batch_returns(batches, returns, *, through_date=None):
    """Reconcile explicit return events against latest saved batch ledger.

    Deduplicate by event identity. If upstream event_id is absent, use
    (operator, batch, return time); never count an event without a batch and
    timestamp. Date filtering uses the same Asia/Kolkata normalization as
    the Daily work source. Current ledger counts are compared only for the
    uncut cumulative view, not for historical as-of dates.
    """
    if through_date is not None:
        date.fromisoformat(through_date)
    ledger = {}
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        ident = str(batch.get('batch_id') or '').strip()
        if not ident:
            continue
        if ident in ledger:
            raise ValueError('Duplicate batch identity in source ledger')
        ledger[ident] = batch

    by_batch = defaultdict(list)
    observed_ids = set()
    duplicates = 0
    invalid = 0
    later = 0
    for entry in returns:
        if not isinstance(entry, dict):
            invalid += 1
            continue
        batch_id = str(entry.get('batch_id') or '').strip()
        try:
            stamp = instant(entry.get('returned_at'))
        except (ValueError, TypeError, OverflowError):
            stamp = None
        if not batch_id or stamp is None:
            invalid += 1
            continue
        if through_date is not None and stamp.date().isoformat() > through_date:
            later += 1
            continue
        # The upstream feed exposes a return timestamp, not a documented
        # globally stable event ID. Our existing event_id is synthesized with
        # the *viewer's* user ID. The same batch return can therefore occur in
        # two operators' histories with different synthetic event IDs.
        # Count one distinct batch+return-time occurrence, not one per viewer.
        identity = (batch_id, stamp.isoformat())
        if identity in observed_ids:
            duplicates += 1
            continue
        observed_ids.add(identity)
        by_batch[batch_id].append(stamp)

    rows = []
    for batch_id in sorted(set(ledger) | set(by_batch)):
        item = ledger.get(batch_id)
        stamps = sorted(by_batch.get(batch_id, ()))
        count = len(stamps)
        recorded = item.get('return_count') if item else None
        if recorded is not None:
            if isinstance(recorded, bool):
                recorded = None
            else:
                try:
                    recorded = int(recorded)
                except (TypeError, ValueError):
                    recorded = None
        compare = item is not None and through_date is None and recorded is not None
        rows.append({
            'batch_id': batch_id,
            'batch_date': item.get('batch_date') if item else None,
            'canonical_user': item.get('canonical_user') if item else None,
            'latest_status': item.get('status') if item else None,
            'ledger_match': item is not None,
            'observed_return_count': count,
            'first_observed_return': stamps[0].isoformat() if stamps else None,
            'last_observed_return': stamps[-1].isoformat() if stamps else None,
            'observed_return_dates': len({stamp.date() for stamp in stamps}),
            'ledger_return_count': recorded,
            'ledger_discrepancy': (count - recorded) if compare else None,
        })
    matched = [row for row in rows if row['ledger_match']]
    unlinked = [row for row in rows if not row['ledger_match']]
    mismatches = [row for row in matched if row['ledger_discrepancy'] not in (None, 0)]
    return {
        'through_date': through_date,
        'coverage': 'observed_events_only',
        'complete_lifetime_history': False,
        'records': rows,
        'summary': {
            'batch_ledger_count': len(ledger),
            'batches_with_observed_returns': sum(row['observed_return_count'] > 0 for row in rows),
            'batches_with_multiple_returns': sum(row['observed_return_count'] >= 2 for row in rows),
            'distinct_observed_returns': len(observed_ids),
            'duplicate_event_documents': duplicates,
            'unusable_event_documents': invalid,
            'after_cutoff_documents': later,
            'unlinked_batch_count': len(unlinked),
            'unlinked_event_count': sum(row['observed_return_count'] for row in unlinked),
            'ledger_mismatch_batches': len(mismatches) if through_date is None else None,
        },
    }

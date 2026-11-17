"""Month-to-date rework history from saved return occurrences and current ledger.

Report event dates in India time. Status is explicitly the batch's *latest*
state, not a reconstructed state at the time the return occurred. This source
does not provide reviewer identity, additional time worked, or a complete
lifetime return history (upstream is capped at 100 per operator).
"""
from collections import defaultdict
from datetime import date, timedelta

from slicing_dashboard.processing.batch_return_history import occurrence_identity
from slicing_dashboard.processing.daily_work import instant


PENDING_REVIEW_STATUSES = frozenset({
    'batch_reviewing', 'batch_pending_leader_review',
    'batch_pending_auditor_review', 'batch_pending_admin_review',
})
STATES = ('Completed', 'Pending Review', 'Other / Unlinked')
EXCLUDED_NAMES = frozenset({
    'admin', 'test', 'dep', 'exempt', 'user-none', '(unassigned)',
})


def _status(batch):
    if not batch:
        return 'Other / Unlinked'
    if batch.get('status') == 'batch_completed':
        return 'Completed'
    if batch.get('status') in PENDING_REVIEW_STATUSES:
        return 'Pending Review'
    return 'Other / Unlinked'


def monthly_return_history(batches, returns, start, end, *,
                           resolve=None, selected_users=None):
    """Exact observed return history for a bounded date range.

    A current-status split is available for every dated event linked to a
    ledger batch. Unmatched or no-longer-reviewing rows are kept visible in
    Other / Unlinked; never silently classified as pending review.
    """
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last - first).days > 31:
        raise ValueError('Monthly return history requires at most 32 days')
    ledger = {}
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        batch_id = str(batch.get('batch_id') or '').strip()
        if not batch_id:
            continue
        if batch_id in ledger:
            raise ValueError('Duplicate batch identity in source ledger')
        ledger[batch_id] = batch

    chosen = set(selected_users) if selected_users is not None else None
    dates = [(first + timedelta(days=offset)).isoformat()
             for offset in range((last - first).days + 1)]
    days = {day: {status: set() for status in STATES} for day in dates}
    batch_events = defaultdict(list)
    all_observed = defaultdict(set)
    seen = set()
    duplicated = invalid = omitted = 0
    for event in returns:
        if not isinstance(event, dict):
            invalid += 1
            continue
        batch_id = str(event.get('batch_id') or '').strip()
        try:
            stamp = instant(event.get('returned_at'))
        except (ValueError, TypeError, OverflowError):
            stamp = None
        if not batch_id or stamp is None:
            invalid += 1
            continue
        identity = occurrence_identity(event, stamp)
        if identity in seen:
            duplicated += 1
            continue
        seen.add(identity)
        if stamp.date() > last:
            continue
        item = ledger.get(batch_id)
        member = (resolve(item) if resolve is not None and item else
                  item.get('canonical_user') if item else None)
        if member and str(member).casefold() in EXCLUDED_NAMES:
            continue
        if chosen is not None and (member not in chosen):
            continue
        all_observed[batch_id].add(identity)
        day = stamp.date().isoformat()
        if day < start:
            continue
        state = _status(item)
        days[day][state].add(identity)
        batch_events[batch_id].append((stamp, state, member, item))

    rows = []
    for batch_id, events in sorted(batch_events.items()):
        events.sort(key=lambda entry: entry[0])
        item = events[0][3]
        rows.append({
            'Batch': batch_id,
            'Member': str(events[0][2] or 'Unlinked'),
            'Latest Status': events[0][1],
            'Returns This Month': len(events),
            'Total Observed Returns Through End': len(all_observed[batch_id]),
            'First Return This Month': events[0][0].isoformat(timespec='seconds'),
            'Latest Return This Month': events[-1][0].isoformat(timespec='seconds'),
            'Batch Date': item.get('batch_date') if item else None,
            'Ledger Linked': bool(item),
        })
    rows.sort(key=lambda row: (-row['Returns This Month'],
                              row['Latest Return This Month'], row['Batch']), reverse=False)

    daily = []
    totals = {state: 0 for state in STATES}
    for day in dates:
        result = {'date': day}
        for state in STATES:
            n = len(days[day][state])
            result[state] = n
            totals[state] += n
        result['total'] = sum(result[state] for state in STATES)
        daily.append(result)

    return {
        'start': start, 'end': end,
        'coverage': 'observed_return_events_only',
        'complete_lifetime_history': False,
        'status_basis': 'latest_batch_status',
        'daily': daily,
        'batches': rows,
        'summary': {
            'observed_returns': sum(totals.values()),
            'affected_batches': len(rows),
            'repeat_return_batches_this_month':
                sum(row['Returns This Month'] >= 2 for row in rows),
            'completed_state_returns': totals['Completed'],
            'pending_review_state_returns': totals['Pending Review'],
            'other_or_unlinked_returns': totals['Other / Unlinked'],
            'unlinked_batches': sum(not row['Ledger Linked'] for row in rows),
            'duplicate_documents_ignored': duplicated,
            'unusable_documents_ignored': invalid,
        },
    }

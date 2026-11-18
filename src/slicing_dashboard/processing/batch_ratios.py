"""Batch proportions use identified batches, never estimates from video hours."""
from collections import defaultdict
from datetime import date
from math import isfinite

import pandas as pd

from slicing_dashboard.processing.daily_work import instant
from slicing_dashboard.processing.batch_return_history import occurrence_identity
from slicing_dashboard.processing.pending_review import number


def batch_ratios(batches, returns, start, end, resolve):
    date.fromisoformat(start)
    date.fromisoformat(end)
    # Compare observed return occurrences with the current ledger before
    # allocating a tier. IMPORTANT: the Collector can itself populate the
    # ledger return_count from these same observations. Equality alone then
    # proves consistency, NOT independent or lifetime completeness.
    recorded, all_observed, invalid_returns, active_returns = (
        defaultdict(set), defaultdict(set), set(), set())
    for row in returns:
        if not isinstance(row, dict):
            continue
        batch = str(row.get('batch_id') or '').strip()
        if not batch:
            continue
        try:
            stamp = instant(row.get('returned_at'))
        except (ValueError, TypeError, OverflowError):
            stamp = None
        if stamp is None:
            invalid_returns.add(batch)
            continue
        identity = occurrence_identity(row, stamp)
        all_observed[batch].add(identity)
        if stamp.date().isoformat() <= end:
            recorded[batch].add(identity)
        if start <= stamp.date().isoformat() <= end:
            active_returns.add(batch)
    totals = {}
    seen = set()
    for batch in batches:
        identifier = batch.get('batch_id')
        if not identifier or identifier in seen:
            raise ValueError('Missing or duplicate batch identity')
        seen.add(identifier)
        day = str(batch.get('batch_date') or '')
        if not (start <= day <= end or identifier in active_returns):
            continue
        status = batch.get('status', '')
        submitted = (status in {'batch_completed', 'batch_rework', 'batch_reviewing',
                     'batch_pending_leader_review', 'batch_pending_auditor_review', 'batch_pending_admin_review'}
                     or any(number(batch.get(field, 0), count=True) > 0 for field in
                            ('completed_count', 'pending_review_count', 'return_count', 'rework_count'))
                     or identifier in active_returns)
        if not submitted:
            continue
        user = resolve(batch)
        if not user or str(user).casefold() in {'admin', 'test', 'dep', 'exempt', 'user-none', '(unassigned)'}:
            continue
        state = 'Completed' if status == 'batch_completed' else 'Pending approvals'
        total = totals.setdefault((user, state), {'tiers': [0] * 5, 'count': 0, 'seconds': 0.,
                                         '3+ returns': 0, 'ids': [set() for _ in range(5)],
                                         'tier_seconds': [0.] * 5})
        total['count'] += 1
        seconds = number(batch.get('total_duration_seconds'))
        total['seconds'] += seconds
        return_count = len(recorded[identifier])
        # The ledger is the independent completeness check. Missing, invalid,
        # or mismatching counts, and unusable dated events, go to Unknown.
        raw_ledger = batch.get('return_count')
        try:
            ledger_number = float(raw_ledger)
            ledger_valid = (not isinstance(raw_ledger, bool) and
                            isfinite(ledger_number) and ledger_number >= 0 and
                            ledger_number == int(ledger_number))
        except (ValueError, TypeError, OverflowError):
            ledger_valid = False
        ledger_count = int(ledger_number) if ledger_valid else None
        verified = (ledger_valid and ledger_count == len(all_observed[identifier])
                    and identifier not in invalid_returns)
        tier = min(3, return_count) if verified else 4
        total['tiers'][tier] += 1
        total['tier_seconds'][tier] += seconds
        account = str(batch.get('username') or batch.get('assignee_id') or '').strip()
        total['ids'][tier].add(account or 'Unavailable')
        if verified and return_count >= 3:
            total['3+ returns'] += return_count
    rows = []
    tier_names = ['No Rework', '1 Rework', '2 Reworks', '3+ Reworks', 'Unknown']
    for (user, state), total in sorted(totals.items()):
        hours = total['seconds'] / 3600
        rows.append({'User': user, 'Completion State': state, **dict(zip(tier_names, total['tiers'])),
                     'Tier IDs': {tier: ', '.join(sorted(ids)) for tier, ids in zip(tier_names, total['ids'])},
                     'Tier Duration (hrs)': {tier: seconds / 3600 for tier, seconds in
                                             zip(tier_names, total['tier_seconds'])},
                     '3+ Return Count': total['3+ returns'],
                     'Total Batches': total['count'], 'Total Duration (hrs)': hours,
                     'Avg Batch Duration (hrs)': hours / total['count']})
    return pd.DataFrame(rows)

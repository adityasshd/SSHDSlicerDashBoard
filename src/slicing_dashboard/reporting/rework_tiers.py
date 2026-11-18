"""Shared rework classification and exact tier durations for charts and KPIs."""
from math import isclose


TIERS = ('No Rework', '1 Rework', '2 Reworks', '3+ Reworks')
DISPLAY_TIERS = (*TIERS, 'Unknown')
LEGACY_UPPER = ('3 Reworks', '4 Reworks', '5+ Reworks')


def _tier_hours(row, sources, count):
    """Older captures lack tier durations; never allocate the person's total by count."""
    from slicing_dashboard.plots.guardrails import finite_number
    if not count:
        return 0.
    durations = row.get('Tier Duration (hrs)')
    if not isinstance(durations, dict):
        return None
    values = [finite_number(durations.get(tier)) for tier in sources if row.get(tier, 0)]
    return sum(values) if values and all(value is not None for value in values) else None


def _tier_ids(row, sources):
    scoped = row.get('Tier IDs')
    if not isinstance(scoped, dict):
        return set()
    return {account.strip() for tier in sources for account in str(scoped.get(tier) or '').split(',')
            if account.strip()}


def prepare_rework_stacks(frame):
    """Fold legacy tiers, keeping completion states and exact return weights separate."""
    combined = {}
    for row in frame.to_dict('records'):
        counts = [row.get('No Rework', 0), row.get('1 Rework', row.get('Reworked Once', 0)),
                  row.get('2 Reworks', row.get('Reworked Twice+', 0))]
        sources = [[tier] for tier in TIERS[:3]]
        if '3+ Reworks' in row:
            upper = row['3+ Reworks']
            upper_weight = row.get('3+ Return Count', upper * 3)
            sources.append(['3+ Reworks'])
        else:
            upper = sum(row.get(tier, 0) for tier in LEGACY_UPPER)
            five = row.get('5+ Reworks', 0)
            five_weight = row.get('5+ Return Count', five * 5)
            if five_weight < five * 5 or (five == 0 and five_weight != 0):
                raise ValueError('Invalid return count for the legacy 5+ rework tier')
            upper_weight = row.get('3 Reworks', 0) * 3 + row.get('4 Reworks', 0) * 4 + five_weight
            sources.append(list(LEGACY_UPPER))
        counts.append(upper)
        # A verified-capture batch can also be unclassifiable. Legacy saved
        # frames omit Unknown; those frames remain readable until refreshed.
        counts.append(row.get('Unknown', 0))
        sources.append(['Unknown'])
        if any(value < 0 or value != int(value) for value in counts) or sum(counts) != row['Total Batches']:
            raise ValueError('Rework tiers do not match submitted batch totals')
        if upper_weight < upper * 3 or (upper == 0 and upper_weight != 0) or upper_weight != int(upper_weight):
            raise ValueError('Invalid return count for the 3+ rework tier')
        weights = [counts[0], counts[1], counts[2] * 2, upper_weight, 0]
        hours_by_tier = [_tier_hours(row, scoped, count) for scoped, count in zip(sources, counts)]
        if 'Total Duration (hrs)' in row and all(hours is not None for hours in hours_by_tier):
            from slicing_dashboard.plots.guardrails import finite_number
            duration = finite_number(row['Total Duration (hrs)'])
            if duration is None or not isclose(sum(hours_by_tier), duration, rel_tol=1e-9, abs_tol=1e-7):
                raise ValueError('Tier durations do not match the batch duration total')
        key = (row['User'], row.get('Completion State'))
        result = combined.setdefault(key, {'counts': [0] * 5, 'weights': [0] * 5,
            'hours': [0.] * 5, 'ids': [set() for _ in DISPLAY_TIERS], 'total': 0})
        result['total'] += row['Total Batches']
        for index, (count, weight, scoped, hours) in enumerate(zip(counts, weights, sources, hours_by_tier)):
            result['counts'][index] += count
            result['weights'][index] += weight
            result['hours'][index] = (result['hours'][index] + hours
                                    if result['hours'][index] is not None and hours is not None else None)
            result['ids'][index].update(_tier_ids(row, scoped))
    return combined


def rework_hours(frame):
    """Sum batch hours once per return tier across users and completion states.

    Older captures without tier durations remain unknown. Never allocate a
    person's hours by batch counts or multiply video hours by return counts.
    """
    from slicing_dashboard.plots.guardrails import checked_frame

    if frame is not None and frame.attrs.get('chart_error'):
        raise ValueError('Rework source unavailable')
    numeric = ['Total Batches', *DISPLAY_TIERS, *LEGACY_UPPER, '3+ Return Count', '5+ Return Count',
               'Reworked Once', 'Reworked Twice+']
    frame = checked_frame(frame, ['User', 'Total Batches'], numeric)
    if frame.empty:
        return dict.fromkeys(DISPLAY_TIERS, 0.0)
    frame = frame[frame['Total Batches'] > 0]
    grouping = ['User', 'Completion State'] if 'Completion State' in frame else ['User']
    if 'Completion State' in frame and not frame['Completion State'].isin(['Completed', 'Pending approvals']).all():
        raise ValueError('Unknown batch completion state')
    if frame.duplicated(grouping).any():
        raise ValueError('Duplicate user batch totals')
    totals = dict.fromkeys(DISPLAY_TIERS, 0.0)
    for stack in prepare_rework_stacks(frame).values():
        for tier, hours in zip(DISPLAY_TIERS, stack['hours']):
            totals[tier] = totals[tier] + hours if totals[tier] is not None and hours is not None else None
    return totals




def rework_counts(frame):
    """Return verified/Unknown BATCH COUNTS, never source video durations.

    Older captures without the Unknown column remain readable. Missing batch
    duration fields cannot invalidate observed return-event counts.
    """
    from slicing_dashboard.plots.guardrails import checked_frame

    if frame is not None and frame.attrs.get('chart_error'):
        raise ValueError('Rework source unavailable')
    frame = checked_frame(frame, ['User', 'Total Batches'],
                          ['Total Batches', *DISPLAY_TIERS, *LEGACY_UPPER,
                           '3+ Return Count', '5+ Return Count',
                           'Reworked Once', 'Reworked Twice+'])
    if frame.empty:
        return dict.fromkeys(DISPLAY_TIERS, 0)
    frame = frame[frame['Total Batches'] > 0]
    group = ['User', 'Completion State'] if 'Completion State' in frame else ['User']
    if 'Completion State' in frame and not frame['Completion State'].isin(
            ['Completed', 'Pending approvals']).all():
        raise ValueError('Unknown batch completion state')
    if frame.duplicated(group).any():
        raise ValueError('Duplicate user batch totals')
    count_only = frame.drop(columns=['Total Duration (hrs)',
                                     'Avg Batch Duration (hrs)',
                                     'Tier Duration (hrs)'], errors='ignore')
    stacks = prepare_rework_stacks(count_only)
    return {tier: sum(stack['counts'][index] for stack in stacks.values())
            for index, tier in enumerate(DISPLAY_TIERS)}

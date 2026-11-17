"""Order summary data like the overview, without changing shared source totals."""
import math


KPI_FIELDS = (
    'total_approved_duration', 'prev_approved_duration', 'approved_pct',
    'assigned_now_duration', 'assigned_duration', 'rework_assigned_duration',
    'total_pending_duration', 'leader_review_duration', 'auditor_review_duration',
    'admin_review_duration',
    'assignable_duration', 'assignable_count', 'assignable_error', 'assignable_captured_at',
    'rework_duration', 'prev_rework_duration', 'rework_pct',
    'total_error_duration', 'prev_error_duration', 'error_pct',
)


def ordered_kpis(kpis, funnel_map):
    """Keep existing keys; derive current assignment data from the existing funnel.

    The funnel is global current work, independent of the selected review period.
    Missing assignment data remains unknown rather than appearing as zero.
    Older saved captures can use this same mapping at render time.
    """
    result = dict(kpis)
    if 'assigned_now_duration' not in result:
        for field, stage in (('assigned_duration', 'assigned'), ('rework_assigned_duration', 'rework')):
            try:
                seconds = float((funnel_map.get(stage) or {})['duration_seconds'])
                result[field] = seconds if math.isfinite(seconds) and seconds >= 0 else None
            except (KeyError, TypeError, ValueError):
                result[field] = None
        assigned, rework = result['assigned_duration'], result['rework_assigned_duration']
        result['assigned_now_duration'] = assigned + rework if assigned is not None and rework is not None else None
    return {field: result[field] for field in KPI_FIELDS if field in result} | {
        field: value for field, value in result.items() if field not in KPI_FIELDS
    }

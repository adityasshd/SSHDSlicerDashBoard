"""Compact, scoped chart captures. Reading a saved panel never contacts a source."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from hashlib import sha256
import json
from threading import RLock

import pandas as pd

from slicing_dashboard.management.periods import today_iso
from slicing_dashboard.processing.daily_work import EXCLUDED

KINDS = ('summary', 'completion', 'rework', 'assigned', 'pending')
VERSION = 2
_LOCK = RLock()
FRAME_COLUMNS = {
    'completion': ('User', 'Completed Duration', 'Completed Tasks'),
    'pending': ('User', 'Stage', 'Duration', 'Count', 'IDs'),
    'assigned': ('User', 'Stage', 'Duration', 'Count', 'IDs', 'ID', 'AssignedDate', 'DaysAssigned',
                 'AssignmentDateBasis', 'ReturnedDate', 'DaysReturned'),
    'rework': ('User', 'Completion State', 'Total Batches', 'No Rework', '1 Rework', '2 Reworks', '3+ Reworks', 'Unknown',
               '3+ Return Count', 'Tier Duration (hrs)', '3 Reworks',
               '4 Reworks', '5+ Reworks', '5+ Return Count', 'Reworked Once', 'Reworked Twice+',
               'Total Duration (hrs)', 'Avg Batch Duration (hrs)', 'Tier IDs'),
}
SUM_FIELDS = ('total_approved_duration', 'prev_approved_duration',
              'total_pending_duration', 'leader_review_duration', 'auditor_review_duration',
              'admin_review_duration', 'rework_duration', 'prev_rework_duration',
              'total_error_duration', 'prev_error_duration')


def panel_key(manager, kind, start, end, *, as_of_date=None):
    if kind not in KINDS:
        raise ValueError('Unknown dashboard panel')
    scope = [as_of_date or today_iso()] if kind in ('pending', 'assigned') else [start, end]
    identity = [manager.scraper._base_url, manager.settings.admin_username]
    if kind == 'assigned':
        identity.append('return-date-v1')
    if kind == 'rework':
        identity.append('verified-return-tiers-with-unknown-v1')
    if kind == 'pending':
        identity.append('recovered-task-timing-v1')
    mapping = [manager.user_mapping, getattr(manager, 'user_mapping_full', {}),
               sorted(getattr(manager, 'exempt_ids', set()))]
    return sha256(json.dumps([VERSION, kind, scope, identity, mapping], sort_keys=True).encode()).hexdigest()


def saved_panel(manager, kind, start, end):
    key = panel_key(manager, kind, start, end)
    with _LOCK:
        return deepcopy(manager._snapshot_payload.get('dashboard_panels', {}).get(key))


def latest_saved_panel(manager, kind, start, end, *, max_age_days=7):
    """Viewer-only fallback for an unavailable *current-day* chart capture.

    Uses the exact same source/mapping identity as normal scoped packets. For
    summary/completion/rework the reporting period must begin at the same start
    date; for current inventory the older date-specific snapshot key is used.
    No snapshot is relabelled as current and custom/historical ranges never
    receive another period's data.
    """
    if end != today_iso() or max_age_days < 1:
        return None
    try:
        start_day, requested_day = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    if start_day > requested_day:
        return None
    india = ZoneInfo("Asia/Kolkata")
    with _LOCK:
        panels = manager._snapshot_payload.get('dashboard_panels', {})
        for age in range(1, max_age_days + 1):
            candidate = requested_day - timedelta(days=age)
            if candidate < start_day:
                break
            candidate_iso = candidate.isoformat()
            key = panel_key(manager, kind, start, candidate_iso, as_of_date=candidate_iso)
            packet = panels.get(key)
            if not isinstance(packet, dict) or not packet.get('available'):
                continue
            # Date from the persisted packet, not the hash, proves when this
            # particular snapshot was actually collected.
            try:
                captured = datetime.fromisoformat(packet['captured_at'].replace('Z', '+00:00'))
                if captured.tzinfo is None or captured.astimezone(india).date() != candidate:
                    continue
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            recovered = deepcopy(packet)
            recovered['fallback'] = {
                'as_of_date': candidate_iso, 'requested_end': end,
                'period_start': start, 'period_end': candidate_iso,
                'age_days': age,
            }
            return recovered
    return None


def attach_panels(manager, payload):
    """Publish a snapshot without losing captures finishing during its assembly.

    The disk/database writer owns an immutable copy; interactive captures can
    keep updating the manager while that slower write runs.
    """
    with _LOCK:
        panels = deepcopy(manager._snapshot_payload.get('dashboard_panels', {}))
        payload['dashboard_panels'] = panels
        manager._snapshot_payload = {**payload, 'dashboard_panels': dict(panels)}


def frame_payload(frame, kind):
    if any(frame.attrs.get(key) for key in ('chart_error', 'pending_error', 'assignment_errors')):
        raise ValueError('Chart source unavailable')
    from slicing_dashboard.plots.guardrails import checked_frame
    required = (['User', 'Completed Duration'] if kind == 'completion' else
                ['User', 'Total Batches'] if kind == 'rework' else ['User', 'Stage', 'Duration'])
    labels = {'User', 'Stage', 'IDs', 'ID', 'AssignedDate', 'ReturnedDate', 'AssignmentDateBasis',
              'Tier IDs', 'Tier Duration (hrs)', 'Completion State'}
    columns = [column for column in FRAME_COLUMNS[kind] if column in frame]
    frame = checked_frame(frame, required, [column for column in columns if column not in labels])
    frame = frame[columns]
    # Preserve IDs needed by stack tooltips; omit task-level audit evidence.
    return {'columns': list(frame.columns), 'records': json.loads(frame.to_json(orient='records'))}


def panel_frame(packet):
    data = packet['data']
    return pd.DataFrame(data['records'], columns=data['columns'])


def selected_summary(data, users, roster):
    result = dict(data['all'])
    if users is None:
        return result
    for field in SUM_FIELDS:
        values = [data['users'].get(user, {}).get(field) for user in users]
        result[field] = sum(values) if all(value is not None for value in values) else None
    for label, current, previous in (
        ('approved', 'total_approved_duration', 'prev_approved_duration'),
        ('error', 'total_error_duration', 'prev_error_duration'),
        ('rework', 'rework_duration', 'prev_rework_duration'),
    ):
        result[label + '_pct'] = (None if result[current] is None or result[previous] is None else
                                 (result[current] - result[previous]) / result[previous] * 100
                                 if result[previous] else 0.0)
    return result


def capture_panel(manager, kind, start, end, force=False):
    """Read just one chart's sources; failures preserve its last successful capture."""
    started = datetime.now(timezone.utc).isoformat()
    try:
        with manager.refresh_scope(persist_snapshot=False):
            key = panel_key(manager, kind, start, end)
            if kind == 'summary':
                all_kpis = manager.get_summary_kpis(start, end, force_refresh=force)
                if all_kpis.get('_source_error'):
                    raise ValueError('Summary unavailable')
                users = set(manager.user_mapping.values()) | set(manager._snapshot_payload.get('available_users', []))
                by_user = {user: manager.get_summary_kpis(start, end, selected_users=[user])
                           for user in sorted(user for user in users if user and user not in EXCLUDED)}
                if any(row.get('_source_error') for row in by_user.values()):
                    raise ValueError('User summary unavailable')
                data = {'all': all_kpis, 'users': by_user, 'funnel': {}}
            elif kind == 'completion':
                data = frame_payload(manager.get_user_breakdown_df(start, end, force), kind)
            elif kind == 'rework':
                data = frame_payload(manager.get_batch_rework_ratio_df(start, end, force_refresh=force), kind)
            elif kind == 'pending':
                data = frame_payload(manager.get_pending_review_df(force_refresh=force), kind)
            elif kind == 'assigned':
                manager.sync_batches_master(start, end, force_refresh=force)
                frame = manager.get_detailed_pending_assigned_df(
                    start_date='2020-01-01', end_date=today_iso(),
                    force_refresh=force, include_pending=False)
                if not frame.empty:
                    frame = frame[frame['Stage'].isin(['New Assigned', 'Rework Assigned'])]
                data = frame_payload(frame, kind)
            else:
                raise ValueError('Unknown dashboard panel')
            if key != panel_key(manager, kind, start, end):
                raise ValueError('Chart mapping or scope changed during capture')
        packet = {'available': True, 'data': data, 'started_at': started,
                  'captured_at': datetime.now(timezone.utc).isoformat()}
        with _LOCK:
            panels = manager._snapshot_payload.setdefault('dashboard_panels', {})
            if panels.get(key, {}).get('started_at', '') <= started:
                panels[key] = deepcopy(packet)
                # Bound snapshot growth when users explore many custom periods.
                for old in sorted(panels, key=lambda item: panels[item]['started_at'])[:-60]:
                    del panels[old]
        return packet
    except Exception as error:
        return {'available': False, 'error': type(error).__name__, 'started_at': started}

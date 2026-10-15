"""Read retained collector output without running or publishing source captures."""
from threading import RLock
from time import perf_counter

from slicing_dashboard.runtime import viewer_mode

_READ_LOCK = RLock()
SNAPSHOT_TTL_SECONDS = 60


def refresh_saved_state(manager, force=False):
    """Share one snapshot read across the callbacks started by a page/Refresh.

    The short forced-read window coalesces a single click's parallel callbacks.
    Failed database reads retain the last good snapshot and expose an error.
    """
    if not viewer_mode():
        return
    with _READ_LOCK:
        ttl = 2 if force else SNAPSHOT_TTL_SECONDS
        if perf_counter() - manager.__dict__.get('_viewer_checked_at', -float('inf')) < ttl:
            return
        manager._viewer_checked_at = perf_counter()
        try:
            snapshot = manager.db.load_dashboard_snapshot()
            if not isinstance(snapshot, dict) or not snapshot:
                raise ConnectionError('Saved dashboard snapshot unavailable')
            cache = snapshot.get('cache', {})
            daily_cache = snapshot.get('daily_cache', {})
            batches = snapshot.get('batches_master_records', [])
            returns = snapshot.get('batch_returns_records', [])
            if not isinstance(cache, dict) or not isinstance(daily_cache, dict):
                raise ValueError('Invalid saved caches')
            if not isinstance(batches, list) or not isinstance(returns, list):
                raise ValueError('Invalid saved ledgers')
            if not isinstance(snapshot.get('dashboard_panels', {}), dict):
                raise ValueError('Invalid saved panels')
            state = {'_snapshot_payload': snapshot, '_cache': dict(cache),
                     '_daily_cache': dict(daily_cache),
                     '_batches_master_cache': {row['batch_id']: row for row in batches
                                               if isinstance(row, dict) and row.get('batch_id')},
                     '_batch_returns_cache': returns,
                     '_batches_master_synced_dates': set(snapshot.get('batches_master_synced_dates', [])),
                     'last_sync_time': snapshot.get('last_sync_time', 'Unknown')}
            manager.__dict__.update(state)
            for name in ('_saved_daily_report_cache', '_user_report_cache', '_dashboard_trend_cache',
                         '_efficiency_history_cache', '_saved_approval_data', '_user_batches_cache'):
                manager.__dict__.pop(name, None)
            manager._viewer_storage_error = None
        except Exception:
            manager._viewer_storage_error = 'Saved data could not be reloaded; showing the last available capture.'
        manager.refresh_shared_configuration(force=force)


def register_viewer_routes(server, manager):
    from flask import request

    @server.before_request
    def reload_saved_reports():
        if viewer_mode() and request.path == '/_dash-update-component':
            payload = request.get_json(silent=True) or {}
            force = 'refresh-btn.n_clicks' in payload.get('changedPropIds', [])
            refresh_saved_state(manager, force=force)

    @server.after_request
    def cache_static_resources(response):
        # Only shared scripts/styles enter the CDN. Report payloads stay private.
        if request.path.startswith('/_dash-component-suites/') and response.status_code == 200:
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            response.headers['Vercel-CDN-Cache-Control'] = 'public, s-maxage=31536000'
        elif request.path.startswith('/_dash-'):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

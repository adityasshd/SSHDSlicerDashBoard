"""Saved first paint, late status changes, failed checks and request races."""
from unittest.mock import MagicMock

import dash
import pytest

from slicing_dashboard.pages.dashboard_trend import register_dashboard_trend


def callbacks():
    app = dash.Dash(__name__)
    manager = MagicMock()
    render = MagicMock(side_effect=lambda data, *args: (data, 'Recorded history.'))
    return app, manager, render, register_dashboard_trend(app, manager, render)


def packet(request_id='first'):
    return {'request_id': request_id, 'range_start': '2026-10-06', 'range_end': '2026-10-08',
            'force_refresh': True, 'approvals': {'rows': [{'stage': 'Admin'}]},
            'efficiency_history': [{'date': '2026-10-06', 'rows': [{'completed_duration_seconds': 60}],
                                    'metadata': {'available': True}}]}


def test_saved_chart_paints_before_capture_and_theme_changes_do_not_repeat_capture():
    app, manager, render, (paint, capture, update) = callbacks()
    data = packet()
    figure, note, ready = paint(data, None, 0, '/', None, None)
    assert figure == data and 'Checking latest completion' in note
    manager.get_efficiency_history.assert_not_called()
    callback = next(value for key, value in app.callback_map.items() if 'dashboard-trend-ready.data' in key)
    assert 'dashboard-trend-live' not in {entry['id'] for entry in callback['inputs']}
    assert paint(data, None, 1, '/', None, ready)[2] is dash.no_update
    manager.get_efficiency_history.return_value = [{
        'date': '2026-10-08', 'rows': [{'completed_duration_seconds': 120}], 'metadata': {'available': True}}]
    manager.get_approval_data.return_value = {'rows': [{'stage': 'Admin', 'date': '2026-10-08'}]}
    live = capture(ready, data)
    manager.get_efficiency_history.assert_called_once_with('2026-10-06', '2026-10-08', force_refresh=True)
    manager.get_approval_data.assert_called_once_with('2026-10-06', '2026-10-08',
                                                    refresh_batches=True, force_refresh=True)
    assert update(live, data, None, 1, '/')[0]['efficiency_history'][-1]['rows'][0]['completed_duration_seconds'] == 120
    assert paint(data, None, 1, '/', live, ready)[0] == live


def test_old_date_response_cannot_replace_new_range_or_refresh_request():
    _, manager, render, (paint, capture, update) = callbacks()
    old, new = packet(), packet('second')
    ready = paint(old, None, 0, '/', None, None)[2]
    with pytest.raises(dash.exceptions.PreventUpdate):
        capture(ready, new)
    with pytest.raises(dash.exceptions.PreventUpdate):
        update(old, new, None, 0, '/')
    manager.get_efficiency_history.assert_not_called()


def test_failed_read_preserves_saved_completion_and_approval_without_fake_zeros():
    _, manager, render, (paint, capture, update) = callbacks()
    data = packet()
    manager.get_efficiency_history.return_value = []
    manager.get_approval_data.return_value = {'error': 'ApprovalReadFailed'}
    ready = paint(data, None, 0, '/', None, None)[2]
    live = capture(ready, data)
    assert live['approvals']['rows'] == data['approvals']['rows']
    days = live['efficiency_history']
    assert days[0]['rows'][0]['completed_duration_seconds'] == 60
    assert all(day['metadata']['error'] for day in days)
    assert all(day['metadata']['available'] is False for day in days[1:])

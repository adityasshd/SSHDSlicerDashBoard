"""Historical dashboard callbacks must never fall back to live source reads."""
from unittest.mock import MagicMock, patch

import dash
import pytest

from slicing_dashboard.pages.dashboard_panels import KINDS
from tests.test_daily_report_page import application_namespace


def test_closed_period_panels_use_only_frozen_packets():
    namespace, manager = application_namespace()
    callback = next(value for key, value in namespace["app"].callback_map.items()
                    if "dashboard-panel-request.data" in key)
    saved = {kind: {"available": True, "data": {"source": "frozen"},
                    "captured_at": "2026-09-30T18:10:00+00:00"}
             for kind in KINDS}
    with patch("slicing_dashboard.pages.dashboard_panels.period_for_range",
               return_value={"settled": True}), \
         patch("slicing_dashboard.pages.dashboard_panels.manager_snapshot",
               return_value={"panels": saved}) as read, \
         patch("dash.ctx", MagicMock(triggered_id="refresh-btn")):
        request, pending_request, *stored = callback["callback"].__wrapped__(
            "2026-09-01", "2026-09-30", 1, 1, "/", 0, 0)
    assert request["frozen"] is True
    assert pending_request == request
    assert all(packet["data"]["source"] == "frozen" for packet in stored)
    read.assert_called_once_with(manager, "2026-09-01", "2026-09-30")
    manager.fetch_dashboard_data.assert_not_called()
    manager.get_pending_review_df.assert_not_called()


def test_frozen_period_never_starts_capture_even_on_refresh():
    namespace, manager = application_namespace()
    callbacks = namespace["app"].callback_map
    request = {"id": "frozen", "start": "2026-09-01",
               "end": "2026-09-30", "frozen": True}
    capture = callbacks["dashboard-live-completion.data"]["callback"].__wrapped__
    with pytest.raises(dash.exceptions.PreventUpdate):
        capture({"request_id": "frozen"}, request)
    paint = next(value for key, value in callbacks.items()
                 if "dashboard-ready-completion.data" in key)["callback"].__wrapped__
    # Missing snapshot gets an explicit unavailable state, never a fresh capture.
    _, status, _, ready, _ = paint(request, {"available": False, "request_id": "frozen"},
                                None, 0, None, None, None, None, "/", None)
    assert ready is dash.no_update
    assert "No verified snapshot" in status
    manager.get_user_breakdown_df.assert_not_called()


def test_trend_capture_skipped_when_historical_snapshot_is_frozen():
    from slicing_dashboard.pages.dashboard_trend import register_dashboard_trend
    app = dash.Dash("test_closed_trend")
    manager = MagicMock()
    render = lambda data, *args: (data, "Recorded snapshot.")
    paint, capture, _ = register_dashboard_trend(app, manager, render)
    payload = {"frozen": True, "request_id": "frozen",
               "range_start": "2026-09-01", "range_end": "2026-09-30"}
    fig, note, ready = paint(payload, None, 0, "/", None, None)
    assert fig is payload
    assert ready is dash.no_update
    with pytest.raises(dash.exceptions.PreventUpdate):
        capture({"request_id": "frozen"}, payload)
    manager.get_efficiency_history.assert_not_called()
    manager.get_approval_data.assert_not_called()

"""Missing current-day captures may display explicitly stale saved evidence."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from slicing_dashboard.reporting.dashboard_panels import (
    latest_saved_panel, panel_key, saved_panel,
)
from slicing_dashboard.pages.dashboard_panels import choose_packet, render_panel
from tests.test_dashboard_panels import fixture_manager


@pytest.mark.parametrize("kind", ["summary", "completion", "rework", "assigned", "pending"])
def test_previous_day_fallback_is_explicit_and_does_not_change_original(kind):
    manager = fixture_manager()
    packet = {
        "available": True, "data": {"all": {}, "users": {}, "funnel": {}},
        "captured_at": "2026-11-16T18:17:50+00:00",
        "started_at": "2026-11-16T18:12:00+00:00",
    }
    with patch("slicing_dashboard.reporting.dashboard_panels.today_iso", return_value="2026-11-17"):
        previous = panel_key(manager, kind, "2026-11-01", "2026-11-16",
                             as_of_date="2026-11-16")
        manager._snapshot_payload["dashboard_panels"] = {previous: deepcopy(packet)}
        assert saved_panel(manager, kind, "2026-11-01", "2026-11-17") is None
        result = latest_saved_panel(manager, kind, "2026-11-01", "2026-11-17")
        assert result["fallback"] == {
            "as_of_date": "2026-11-16",
            "requested_end": "2026-11-17",
            "period_start": "2026-11-01",
            "period_end": "2026-11-16",
            "age_days": 1,
        }
        assert "fallback" not in manager._snapshot_payload["dashboard_panels"][previous]
        assert latest_saved_panel(manager, kind, "2026-11-02", "2026-11-17") is None
        # Historic or custom ranges never silently fall back to a different date.
        assert latest_saved_panel(manager, kind, "2026-11-01", "2026-11-15") is None
        assert latest_saved_panel(manager, kind, "2026-11-17", "2026-11-17") is None
        with patch("slicing_dashboard.pages.dashboard_panels.viewer_mode", return_value=True):
            result["request_id"] = "latest"
            selected, status = choose_packet(
                {"id": "latest", "start": "2026-11-01", "end": "2026-11-17"},
                result, None,
            )
            assert selected is result
            assert "STALE" in status and "2026-11-16" in status and "Not current" in status


def test_rejects_unverifiable_capture_dates_and_mapping_changes():
    manager = fixture_manager()
    with patch("slicing_dashboard.reporting.dashboard_panels.today_iso", return_value="2026-11-17"):
        key = panel_key(manager, "pending", "2026-11-01", "2026-11-16",
                        as_of_date="2026-11-16")
        manager._snapshot_payload["dashboard_panels"] = {key: {
            "available": True, "captured_at": "2026-11-17T03:00:00+00:00",
            "data": {"columns": [], "records": []}}}
        assert latest_saved_panel(manager, "pending", "2026-11-01", "2026-11-17") is None
        manager._snapshot_payload["dashboard_panels"][key]["captured_at"] = "2026-11-16T18:00:00+00:00"
        manager.user_mapping["account"] = "Another person"
        assert latest_saved_panel(manager, "pending", "2026-11-01", "2026-11-17") is None


def test_closed_snapshot_never_uses_stale_fallback():
    data = {"available": True, "fallback": {
        "as_of_date": "2026-11-16", "requested_end": "2026-11-17"},
        "request_id": "closed"}
    selected, message = choose_packet({"id": "closed", "frozen": True}, data, None)
    assert selected is data
    assert message == "Final settled-period snapshot · read only"

"""Rework overview shows verified VIDEO HOURS, not historical batch counts.

The return tiers classify whole video duration by observed lifetime batch
returns. They are not hours spent fixing a video, and Unknown is never zero.
Original batch counts remain usable in explicitly separate audit functions.
"""
from copy import deepcopy

import pandas as pd
import pytest

from slicing_dashboard.pages.dashboard_panels import render_rework_hours
from slicing_dashboard.plots.kpi_overview import build_rework_count_metric
from slicing_dashboard.processing.batch_ratios import batch_ratios
from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame
from slicing_dashboard.reporting.rework_tiers import (
    DISPLAY_TIERS, rework_hours, rework_counts,
)
from tests.test_daily_report_page import application_namespace, components, payload_text


REQUEST = {"id": "one"}


def duration_row(user, state, **hours):
    tiers = {tier: 0.0 for tier in DISPLAY_TIERS}
    tiers.update(hours)
    return {
        "User": user, "Completion State": state,
        "Total Batches": 0, "No Rework": 0, "1 Rework": 0,
        "2 Reworks": 0, "3+ Reworks": 0, "Unknown": 0,
        "Verified Tier Duration (hrs)": tiers,
        "Verified Total Seconds": sum(tiers.values()) * 3600,
        "Verified Hours Available": True,
    }


def packet():
    data = pd.DataFrame([
        duration_row("A", "Completed",
                     **{"No Rework": 1, "1 Rework": 2, "Unknown": .25}),
        duration_row("B", "Completed",
                     **{"2 Reworks": 3, "3+ Reworks": 4, "Unknown": .5}),
        duration_row("A", "Pending approvals",
                     **{"1 Rework": .5, "Unknown": .3}),
        duration_row("B", "Pending approvals",
                     **{"2 Reworks": 1.25, "Unknown": 0}),
    ])
    return {
        "available": True, "request_id": "one",
        "captured_at": "2026-10-08T00:00:00Z",
        "data": frame_payload(data, "rework"),
    }


def test_rework_kpi_uses_verified_video_hours_not_batch_counts():
    content = payload_text(render_rework_hours(
        REQUEST, None, packet(), None, 0, completion_state="Completed"))
    assert "Video hours" in content
    assert "09:00:00" in content  # A 2h + B (3+4)h from returned batches
    assert "01:00:00" in content  # No Rework duration
    assert "00:45:00" in content  # Unknown duration: 0.25 + 0.5 hours
    assert "Returned: 5" not in content
    assert "Rework batches" not in content


def test_video_hour_distribution_is_based_on_duration_not_batch_shares():
    content = render_rework_hours(
        REQUEST, None, packet(), None, 0, completion_state="Completed")
    bars = [node for node in components(content)
            if getattr(node, "role", None) == "progressbar"]
    shares = [node.to_plotly_json()["props"]["aria-valuenow"] for node in bars]
    # 1 + 2 + 3 + 4 + .75 = 10.75 hours across known and Unknown tiers.
    assert shares == pytest.approx(
        [100 * amount / 10.75 for amount in (1, 2, 3, 4, .75)],
        abs=.01,
    )


@pytest.mark.parametrize("user,returned", [
    (["A"], "02:00:00"), (["B"], "07:00:00"),
])
def test_selected_users_only_sum_their_verified_video_hours(user, returned):
    content = payload_text(render_rework_hours(
        REQUEST, None, packet(), user, 0, completion_state="Completed"))
    assert returned in content
    assert "Rework batches" not in content


def test_no_users_selected_is_not_fabricated_zero_hours():
    content = payload_text(render_rework_hours(
        REQUEST, None, packet(), [], 0, completion_state="Completed"))
    assert "Video hours" in content
    assert r"\u2014" in content or "—" in content
    assert "09:00:00" not in content


def test_completed_and_pending_are_disjoint_independent_video_inventories():
    completed = payload_text(render_rework_hours(
        REQUEST, None, packet(), None, 0, completion_state="Completed"))
    pending = payload_text(render_rework_hours(
        REQUEST, None, packet(), None, 0, completion_state="Pending approvals"))
    assert "09:00:00" in completed
    assert "01:45:00" in pending
    assert "09:00:00" not in pending
    assert "01:45:00" not in completed


def test_missing_duration_evidence_is_unavailable_not_whole_batch_guess():
    invalid = deepcopy(packet())
    invalid["data"]["records"][0]["Verified Tier Duration (hrs)"] = None
    content = payload_text(render_rework_hours(
        REQUEST, None, invalid, None, 0, completion_state="Completed"))
    assert r"\u2014" in content or "—" in content
    assert "09:00:00" not in content


def test_original_batch_durations_remain_in_separate_audit_but_not_paid_chart():
    batches = [
        dict(batch_id="a", username="A", batch_date="2026-10-01",
             status="batch_completed", total_duration_seconds=150 * 3600,
             return_count=0),
    ]
    frame = batch_ratios(batches, [], "2026-10-01", "2026-10-08",
                         lambda batch: batch["username"])
    assert rework_hours(frame)["No Rework"] == 150
    assert rework_counts(frame)["No Rework"] == 1
    legacy = {"available": True, "request_id": "one",
              "captured_at": "2026-10-08T00:00:00Z",
              "data": frame_payload(frame, "rework")}
    content = payload_text(render_rework_hours(
        REQUEST, None, legacy, None, 0, completion_state="Completed"))
    assert "150:00:00" not in content
    assert r"\u2014" in content or "—" in content


def test_independent_completed_evidence_adds_only_missing_hours_to_unknown():
    evidence = {
        "available": True,
        "rows": [
            {"User": "A", "seconds": 4 * 3600, "tasks": 5},
            {"User": "B", "seconds": 8 * 3600, "tasks": 10},
        ],
    }
    content = payload_text(render_rework_hours(
        REQUEST, None, packet(), None, 0, "Completed", evidence))
    assert "09:00:00" in content  # verified returned hours unchanged
    assert "02:00:00" in content  # Unknown = 12 - (1+9)
    assert "150:00:00" not in content


def test_invalid_completion_source_does_not_invent_rework_hours():
    evidence = {"available": True,
                "rows": [{"User": "A", "seconds": 100, "tasks": 1}]}
    content = payload_text(render_rework_hours(
        REQUEST, None, packet(), ["A"], 0, "Completed", evidence))
    assert r"\u2014" in content or "—" in content
    assert "Completed source and archive disagree" in content


def test_legacy_batch_count_helper_remains_explicit_and_separate():
    content = build_rework_count_metric({
        "No Rework": 90, "1 Rework": 2, "2 Reworks": None,
        "3+ Reworks": 4, "Unknown": 1,
    })
    assert any(node.children == "Returned: —" for node in components(content))
    assert "Breakdown unavailable" in payload_text(content)


def test_refresh_failure_keeps_saved_verified_hours_not_unverified_batch_counts():
    text = payload_text(render_rework_hours(
        REQUEST, packet(), {"request_id": "one", "available": False},
        None, 0, completion_state="Completed"))
    assert "09:00:00" in text
    assert "Latest read failed" in text
    fresh = payload_text(render_rework_hours(
        {"id": "two"}, packet(), None, None, 0, completion_state="Completed"))
    assert "09:00:00" not in fresh
    assert "Loading latest data" in fresh


def test_rework_kpi_callback_does_not_issue_extra_source_reads():
    namespace, manager = application_namespace()
    callback = next(
        item for key, item in namespace["app"].callback_map.items()
        if "dashboard-ready-rework.data" in key
    )
    paint = callback["callback"].__wrapped__
    request = {**REQUEST, "start": "2026-10-01", "end": "2026-10-07"}
    _, _, content, _, _ = paint(
        request, packet(), None, 0, "Completed", None, None, None, "/", None
    )
    assert "09:00:00" in payload_text(content)
    assert manager.get_batch_rework_ratio_df.call_count == 0
    assert manager.fetch_dashboard_data.call_count == 0

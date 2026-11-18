"""Regression tests for evidence-backed video-hour rework heatmaps.

No unverified whole-batch duration is silently assigned to a return tier.
"""
import pandas as pd
import pytest

from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart
from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame
from slicing_dashboard.reporting.verified_duration_heatmaps import (
    TIERS, _match_account_day, _return_tiers, pending_duration_rows,
)


def _fixture_frame():
    hours = {tier: 0.0 for tier in TIERS}
    hours.update({"No Rework": 1.0, "1 Rework": 0.5, "Unknown": 0.25})
    return pd.DataFrame([{
        "User": "Akash", "Completion State": "Completed",
        "Total Batches": 0, "No Rework": 0, "1 Rework": 0,
        "2 Reworks": 0, "3+ Reworks": 0, "Unknown": 0,
        "Verified Tier Duration (hrs)": hours,
        "Verified Total Seconds": 6300.0,
        "Verified Hours Available": True,
        "Verified Source Warning": "",
    }])


def test_completed_heatmap_uses_five_duration_columns_and_conserves_source():
    frame = _fixture_frame()
    f = build_rework_ratio_chart(
        frame, "2026-11-01", True, completion_state="Completed",
        completed_evidence={"available": True, "rows": [
            {"User": "Akash", "seconds": 6300, "tasks": 40},
        ]})
    assert len(f.data) == 1
    assert list(f.data[0].x) == list(TIERS)
    assert f.layout.meta["value_unit"] == "Hours"
    assert all(unit == "hours" for unit in f.layout.meta["column_units"])
    assert f.layout.meta["verified_total_seconds"] == pytest.approx(6300)
    assert f.layout.meta["unknown_duration_seconds"] == pytest.approx(900)
    assert sum(f.layout.meta["tier_duration_seconds"]) == pytest.approx(6300)
    assert f.data[0].y[-1] == "<b>Total</b>"


def test_missing_archive_uses_unknown_column_not_one_completed_line():
    # Even when the rework panel has no batch-attribution rows, the independent
    # Completed Hours source must still keep five columns.
    frame = pd.DataFrame(columns=["Verified Tier Duration (hrs)"])
    fig = build_rework_ratio_chart(
        frame, "2026-11-01", True, completion_state="Completed",
        completed_evidence={"available": True, "rows": [
            {"User": "Akash", "seconds": 3600, "tasks": 20}]})
    assert list(fig.data[0].x) == list(TIERS)
    assert fig.layout.meta["verified_total_seconds"] == pytest.approx(3600)
    assert fig.layout.meta["unknown_duration_seconds"] == pytest.approx(3600)
    assert fig.layout.meta["tier_duration_seconds"][0] == 0


def test_newer_independent_completion_is_conserved_in_unknown():
    fig = build_rework_ratio_chart(
        _fixture_frame(), "2026-11-01", True, completion_state="Completed",
        completed_evidence={"available": True, "rows": [
            {"User": "Akash", "seconds": 6335, "tasks": 41}]})
    assert fig.layout.meta["verified_total_seconds"] == pytest.approx(6335)
    assert fig.layout.meta["unknown_duration_seconds"] == pytest.approx(935)


def test_pending_uses_same_five_hour_columns_without_date_filter():
    values = {tier: 0.0 for tier in TIERS}
    values["1 Rework"] = 2
    frame = pd.DataFrame([{
        "User": "Akash", "Completion State": "Pending approvals",
        "Total Batches": 0, "Verified Tier Duration (hrs)": values,
        "Verified Total Seconds": 7200.0, "Verified Hours Available": True,
        "Verified Source Warning": "",
    }])
    chart = build_rework_ratio_chart(frame, "2026-11-01", True,
                                     completion_state="Pending approvals")
    assert list(chart.data[0].x) == list(TIERS)
    assert chart.layout.meta["date_scope"] == "current_queue"
    assert chart.layout.meta["verified_total_seconds"] == pytest.approx(7200)


def test_legacy_numbers_alone_do_not_prove_return_tiers():
    class Manager:
        @staticmethod
        def _get_reporting_name(uid, username):
            return "Akash"

    pending = [
        {"id": "one", "slicer_id": 21345, "slicer": "SSHD-Akash11",
         "status": "slice_submitted", "slice_batch": 10, "duration_seconds": 50},
        {"id": "two", "slicer_id": 21345, "slicer": "SSHD-Akash11",
         "status": "slice_submitted", "slice_batch": 10, "duration_seconds": 60},
        {"id": "unlinked", "slicer_id": 21345, "slicer": "SSHD-Akash11",
         "status": "slice_pending_admin_review", "slice_batch": 999,
         "duration_seconds": 40},
    ]
    batches = [
        {"batch_id": "ab_example", "assignee_id": 21345,
         "status": "batch_member_assigned", "production_task_count": 2,
         "total_duration_seconds": 110, "benchmark_count": 0},
    ]
    result = pending_duration_rows(Manager(), batches, {"ab_example": "1 Rework"}, pending)
    assert result["Akash"]["1 Rework"] == pytest.approx(110)
    assert result["Akash"]["Unknown"] == pytest.approx(40)
    assert sum(result["Akash"].values()) == pytest.approx(150)


def test_ambiguous_full_batch_match_stays_unknown():
    class Manager:
        @staticmethod
        def _get_reporting_name(uid, username):
            return "Akash"

    tasks = [{"id": "one", "slicer_id": 21345, "slicer": "SSHD-Akash11",
              "status": "slice_pending_auditor_review", "slice_batch": 3,
              "duration_seconds": 150}]
    batches = [
        {"batch_id": bid, "assignee_id": 21345,
         "status": "batch_pending_auditor_review", "production_task_count": 1,
         "total_duration_seconds": 150, "benchmark_count": 0}
        for bid in ("A", "B")
    ]
    result = pending_duration_rows(Manager(), batches, {"A": "No Rework", "B": "2 Reworks"}, tasks)
    assert result["Akash"]["Unknown"] == 150
    assert result["Akash"]["No Rework"] == 0


def test_return_tiers_require_deduplicated_events_and_matching_ledger():
    batches = [{"batch_id": "A", "return_count": 0},
               {"batch_id": "B", "return_count": 2},
               {"batch_id": "C", "return_count": 1}]
    event = {"batch_id": "C", "returned_at": "2026-11-16T10:00:00Z"}
    tiers = _return_tiers(batches, [event, dict(event)])
    assert tiers == {"A": "No Rework", "C": "1 Rework"}
    assert _return_tiers(batches, [event], False) == {}


def test_multi_batch_matching_requires_unique_count_and_duration():
    options = {"19001": [
        {"bid": "A", "count": 20, "seconds": 3600},
        {"bid": "B", "count": 19, "seconds": 3700},
    ]}
    found = _match_account_day("19001", 39, 7300, options)
    assert found is not None
    assert {v["bid"] for v in found} == {"A", "B"}
    ambiguous = {"19001": [
        *options["19001"],
        {"bid": "C", "count": 20, "seconds": 3600},
    ]}
    assert _match_account_day("19001", 39, 7300, ambiguous) is None


def test_panel_storage_preserves_optional_verified_hours_and_unavailable_cells():
    frame = _fixture_frame()
    row = {column: 0 for column in frame.columns if column in
           ("Total Batches", "No Rework", "1 Rework", "2 Reworks", "3+ Reworks", "Unknown")}
    row.update({"User": "Priya", "Completion State": "Completed",
                "Total Batches": 1, "Verified Tier Duration (hrs)": None,
                "Verified Total Seconds": None, "Verified Hours Available": None,
                "Verified Source Warning": "Completed archive: ValueError"})
    frame.loc[len(frame)] = row
    data = frame_payload(frame, "rework")
    restored = panel_frame({"data": data})
    assert restored.loc[0, "Verified Total Seconds"] == 6300
    assert pd.isna(restored.loc[1, "Verified Hours Available"])


def test_partial_assigned_queue_preserves_known_hours_and_warning():
    frame = pd.DataFrame([
        {"User": "Akash", "ID": "SSHD-Akash11", "Stage": "New Assigned",
         "Duration": 3600.0, "Count": 20, "AssignedDate": ""},
    ])
    frame.attrs["assignment_errors"] = ["Rework Assigned: TimeoutError"]
    data = frame_payload(frame, "assigned")
    assert data["queue_complete"] is False
    assert data["source_warnings"] == ["Rework Assigned: TimeoutError"]
    recovered = panel_frame({"data": data})
    assert recovered["Duration"].sum() == pytest.approx(3600)
    assert recovered.attrs["assignment_errors"] == ["Rework Assigned: TimeoutError"]


def test_archived_completed_batch_duration_is_not_zeroed_by_unrelated_queues(monkeypatch):
    from types import SimpleNamespace
    from slicing_dashboard.reporting import verified_duration_heatmaps as module

    class Manager:
        @staticmethod
        def _get_reporting_name(uid, username):
            return "Aditya"

    store = SimpleNamespace()
    day = {"display_date": "2026-11-10", "captured_at": "2026-11-18T13:00:00Z",
           "items": [{"user_id": 4912, "username": "SSHD-Adi",
                      "completed_count": 65, "completed_duration_seconds": 3649}]}
    monkeypatch.setattr(module, "_efficiency_days",
                        lambda store, start, end: {"2026-11-10": day})
    monkeypatch.setattr(module, "_archive_states", lambda store, start, end: [
        {"bid": "ab_test", "uid": "4912", "count": "65", "value": "3649",
         "bench": "0", "completedPeak": 64,
         "statuses": ["batch_completed"]}])
    result = module.completed_duration_rows(
        Manager(), "2026-11-10", "2026-11-10", store, {"ab_test": "No Rework"})
    assert result["Aditya"]["No Rework"] == pytest.approx(3649)
    assert sum(result["Aditya"].values()) == pytest.approx(3649)

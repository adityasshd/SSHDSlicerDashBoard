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
    assert list(f.data[0].x) == [*TIERS, '<b>Total</b>']
    assert f.layout.meta["value_unit"] == "Hours"
    assert all(unit == "hours" for unit in f.layout.meta["column_units"])
    assert f.layout.meta["verified_total_seconds"] == pytest.approx(6300)
    assert f.layout.meta['grand_total'] == pytest.approx(1.75)
    assert f.layout.meta['row_totals'] == pytest.approx([1.75])
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
    assert list(fig.data[0].x) == [*TIERS, '<b>Total</b>']
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
    assert list(chart.data[0].x) == [*TIERS, '<b>Total</b>']
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



def test_assigned_dates_are_categorical_not_numeric():
    """Regression: UpdatedDate (ISO date or blank) previously failed checked_frame."""
    from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame

    row = {
        "User": "Aditya", "ID": "SSHD-Adi", "Stage": "New Assigned",
        "Duration": 3649.0, "Count": 65, "IDs": "SSHD-Adi",
        "AssignedDate": "2026-11-10", "DaysAssigned": 8,
        "AssignmentDateBasis": "Batch assignment date",
        "ReturnedDate": "", "DaysReturned": 0,
        "UpdatedDate": "2026-11-17", "DaysUpdated": 1,
        "UpdateDateBasis": "Task update timestamp",
    }
    packet = frame_payload(pd.DataFrame([row]), "assigned")
    restored = panel_frame({"data": packet})
    assert restored.loc[0, "UpdatedDate"] == "2026-11-17"
    assert restored.loc[0, "AssignedDate"] == "2026-11-10"
    assert restored.loc[0, "Duration"] == pytest.approx(3649.)
    assert restored.loc[0, "DaysUpdated"] == 1

    blank_date = {**row, "UpdatedDate": "", "ReturnedDate": ""}
    packet = frame_payload(pd.DataFrame([blank_date]), "assigned")
    assert packet["records"][0]["UpdatedDate"] == ""


def test_assigned_invalid_video_duration_still_rejected():
    from slicing_dashboard.reporting.dashboard_panels import frame_payload

    frame = pd.DataFrame([{
        "User": "Aditya", "Stage": "New Assigned", "Duration": "invalid",
        "Count": 1, "UpdatedDate": "2026-11-18",
    }])
    with pytest.raises(ValueError, match="Invalid chart values"):
        frame_payload(frame, "assigned")


def test_rework_render_panel_has_no_shadowed_chart_import(monkeypatch):
    """Regression: local import assigned chart name only in the no-packet branch."""
    from slicing_dashboard.pages import dashboard_panels as page

    calls = []
    dummy_figure = object()
    monkeypatch.setattr(page, "choose_packet",
                        lambda request, saved, live: (
                            {"data": {"columns": ["User", "Completion State"],
                                      "records": [{
                                          "User": "Aditya",
                                          "Completion State": "Pending approvals",
                                      }]}}
                            , "Captured"))
    def plot(*args, **kwargs):
        calls.append(kwargs)
        return dummy_figure

    monkeypatch.setattr(page, "build_rework_ratio_chart", plot)
    figure, status = page.render_panel(
        "rework", {"start": "2026-11-01", "end": "2026-11-18"},
        None, None, None, 0, [], completion_state="Pending approvals")
    assert figure is dummy_figure
    assert status == "Captured"
    assert calls[0]["completion_state"] == "Pending approvals"



def test_remote_db_failure_is_not_treated_as_empty_local_sqlite():
    """A failed configured Atlas connection must not invent zero hours."""
    from types import SimpleNamespace
    from slicing_dashboard.reporting.verified_duration_heatmaps import (
        historical_store_unavailable,
    )
    atlas = SimpleNamespace(
        settings=SimpleNamespace(mongo_uri="mongodb+srv://example.invalid",
                                 database_url=None),
        mongo_db=None, engine=None,
    )
    manager = SimpleNamespace(db=atlas)
    assert historical_store_unavailable(manager) is True
    local = SimpleNamespace(
        settings=SimpleNamespace(mongo_uri=None, database_url=None),
        mongo_db=None, engine=None,
    )
    assert historical_store_unavailable(SimpleNamespace(db=local)) is False
    atlas.mongo_db = object()
    assert historical_store_unavailable(manager) is False


def test_incomplete_efficiency_window_raises_missing_coverage_not_zero(monkeypatch):
    from slicing_dashboard.reporting import verified_duration_heatmaps as module

    monkeypatch.setattr(module, "_efficiency_days",
                        lambda *args: {"2026-11-10": {"items": []}})
    with pytest.raises(module.EfficiencyCaptureUnavailable,
                       match=r"missing: 1 of 2"):
        module.completed_duration_rows(
            object(), "2026-11-10", "2026-11-11", object(), {})


def test_db_outage_keeps_independent_pending_duration_and_explains_completed(monkeypatch):
    """Offline Mongo's empty SQLite does not hide a valid live pending queue."""
    from types import SimpleNamespace
    from slicing_dashboard.reporting import verified_duration_heatmaps as module

    class Manager:
        _batches_master_cache = {}
        _batch_returns_cache = []
        _returns_source_error = None
        _batch_source_error = None
        db = SimpleNamespace(
            settings=SimpleNamespace(mongo_uri="mongodb+srv://example.invalid",
                                     database_url=None),
            mongo_db=None, engine=None,
        )
        scraper = object()

        @staticmethod
        def _get_reporting_name(uid, username):
            return "Aditya"

    monkeypatch.setattr(module, "_efficiency_days",
                        lambda *args: pytest.fail("Offline database should not be read"))
    monkeypatch.setattr(module, "capture_for",
                        lambda manager: SimpleNamespace(read=lambda scraper: {
                            "error": None,
                            "tasks": [
                                {"id": "pending1", "slicer_id": 4912,
                                 "slicer": "SSHD-Adi", "status": "slice_submitted",
                                 "slice_batch": 23, "duration_seconds": 90},
                            ],
                        }), raising=False)
    # capture_for is imported inside the function; patch its source module.
    from slicing_dashboard.processing import pending_review
    monkeypatch.setattr(pending_review, "capture_for",
                        lambda manager: SimpleNamespace(read=lambda scraper: {
                            "error": None,
                            "tasks": [
                                {"id": "pending1", "slicer_id": 4912,
                                 "slicer": "SSHD-Adi", "status": "slice_submitted",
                                 "slice_batch": 23, "duration_seconds": 90},
                            ],
                        }))
    frame = module.with_verified_duration(
        Manager(), pd.DataFrame(), "2026-11-01", "2026-11-18")
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["Completion State"] == "Pending approvals"
    assert row["Verified Total Seconds"] == pytest.approx(90)
    assert row["Verified Tier Duration (hrs)"]["Unknown"] == pytest.approx(90 / 3600)
    assert "configured database unavailable" in row["Verified Source Warning"]
    packet = frame_payload(frame, "rework")
    restored = panel_frame({"data": packet})
    assert any("configured database unavailable" in warning
               for warning in restored.attrs["source_warnings"])



def test_empty_offline_archive_warning_survives_panel_serialization():
    """Empty history + no live queue = unavailable, never a false zero total."""
    from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart

    frame = pd.DataFrame(columns=[
        "Verified Tier Duration (hrs)", "Verified Total Seconds",
        "Verified Hours Available", "Verified Source Warning",
    ])
    frame.attrs["source_warnings"] = [
        "Completed archive: configured database unavailable",
        "Pending task queue: ValueError",
    ]
    packet = frame_payload(frame, "rework")
    assert packet["source_warnings"] == frame.attrs["source_warnings"]
    restored = panel_frame({"data": packet})
    assert restored.attrs["source_warnings"] == frame.attrs["source_warnings"]
    figure = build_rework_ratio_chart(
        restored, "2026-11-01", True, completion_state="Completed")
    assert not figure.data
    assert "historical database" in figure.layout.annotations[0].text.lower().replace("<br>", " ")

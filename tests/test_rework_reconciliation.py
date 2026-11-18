"""Cross-check batch events, chart cells and the rework KPI at matching scope."""
from math import isclose

import pandas as pd
import pytest

from slicing_dashboard.processing.batch_ratios import batch_ratios
from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart
from slicing_dashboard.reporting.rework_tiers import TIERS, prepare_rework_stacks, rework_hours
from tests.test_daily_report_page import application_namespace
from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame


def fixture_data():
    batches = [
        {"batch_id": "A1", "batch_date": "2026-11-06", "status": "batch_completed",
         "user": "A", "username": "account-a", "return_count": 2, "total_duration_seconds": 7200},
        {"batch_id": "A2", "batch_date": "2026-11-07",
         "status": "batch_pending_auditor_review", "user": "A",
         "username": "account-a", "return_count": 2, "total_duration_seconds": 14400},
        {"batch_id": "B1", "batch_date": "2026-11-08", "status": "batch_completed",
         "user": "B", "username": "account-b", "return_count": 0, "total_duration_seconds": 21600},
    ]
    returns = [
        {"batch_id": "A1", "event_id": "return-1", "returned_at": "2026-11-06T10:00:00Z"},
        # Same event repeated in the collection: never a second return.
        {"batch_id": "A1", "event_id": "return-1", "returned_at": "2026-11-06T10:00:00Z"},
        {"batch_id": "A2", "event_id": "return-2", "returned_at": "2026-11-07T11:00:00Z"},
        {"batch_id": "A2", "event_id": "return-3", "returned_at": "2026-11-07T12:00:00Z"},
        # Must not affect this November 1-17 reporting period.
        {"batch_id": "A1", "event_id": "return-next", "returned_at": "2026-11-20T12:00:00Z"},
    ]
    return batches, returns


def heatmap_hours(figure):
    assert len(figure.data) == 1  # All columns + neutral Total share cell geometry
    trace = figure.data[0]
    return sum(float(cell[-1]) for row in trace.customdata[:-1]
               for cell in row if cell[-1] is not None)


def test_rework_batch_event_dedup_and_duration_conservation():
    batches, returns = fixture_data()
    frame = batch_ratios(batches, returns, "2026-11-01", "2026-11-17",
                         lambda b: b["user"])
    assert int(frame["Total Batches"].sum()) == 3
    by_user = {(r.User, r["Completion State"]): r for _, r in frame.iterrows()}
    assert by_user["A", "Completed"]["1 Rework"] == 1
    assert by_user["A", "Pending approvals"]["2 Reworks"] == 1
    assert by_user["B", "Completed"]["No Rework"] == 1
    assert frame["Total Duration (hrs)"].sum() == pytest.approx(12.0)
    tiers = rework_hours(frame)
    assert tiers == pytest.approx({"No Rework": 6.0, "1 Rework": 2.0,
                                    "2 Reworks": 4.0, "3+ Reworks": 0.0, "Unknown": 0.0})
    assert sum(tiers.values()) == pytest.approx(frame["Total Duration (hrs)"].sum())
    assert sum(stack["total"] for stack in prepare_rework_stacks(frame).values()) == 3


@pytest.mark.parametrize("state,expected_hours", [
    ("All", 12.0), ("Completed", 8.0), ("Pending approvals", 4.0),
])
@pytest.mark.parametrize("show_counts", [False, True])
def test_rework_matrix_matches_source_hours_for_each_state(state, expected_hours, show_counts):
    batches, returns = fixture_data()
    frame = panel_frame({"data": frame_payload(
        batch_ratios(batches, returns, "2026-11-01", "2026-11-17",
                     lambda batch: batch["user"]), "rework")})
    fig = build_rework_ratio_chart(frame, "2026-11-01", True,
                                   completion_state=state, show_counts=show_counts)
    assert heatmap_hours(fig) == pytest.approx(expected_hours)
    # Colour intensity always measures HOURS even if count annotations are on.
    assert all(trace.showscale is False for trace in fig.data)
    assert fig.layout.meta['color_scope'] == 'per_column'
    assert sum(fig.layout.meta["column_totals"]) == pytest.approx(expected_hours)
    for column in range(5):
        raw = [row[column][-1] for row in fig.data[0].customdata[:-1]]
        assert fig.layout.meta["column_totals"][column] == pytest.approx(sum(
            value for value in raw if value is not None))
        assert fig.layout.meta['column_maxima'][column] == pytest.approx(max(
            [value for value in raw if value is not None] or [0]))
    assert fig.layout.meta["show_counts"] is show_counts
    assert "Each batch duration counted once" in fig.layout.title.subtitle.text
    if state == "All":
        assert "Completed + Pending approvals" in fig.layout.title.subtitle.text


def test_rework_toggle_callback_repaints_without_source_reads():
    namespace, manager = application_namespace()
    handlers = namespace["app"].callback_map
    key = next(key for key in handlers
               if "rework-ratio-chart.figure" in key and "@" not in key)
    callback = handlers[key]
    assert {"id": "rework-completion-state", "property": "value"} in callback["inputs"]
    assert not any(item["id"].endswith("-counts") for item in callback["inputs"])
    batches, returns = fixture_data()
    frame = batch_ratios(batches, returns, "2026-11-01", "2026-11-17",
                         lambda batch: batch["user"])
    packet = {"request_id": "r1", "available": True,
              "captured_at": "2026-11-17T00:00:00+00:00",
              "data": frame_payload(frame, "rework")}
    request = {"id": "r1", "start": "2026-11-01", "end": "2026-11-17"}
    fn = callback["callback"].__wrapped__
    all_fig, _, _, _, _ = fn(request, packet, None, 0, "All", None, None, None, "/", None)
    complete_fig, _, _, _, _ = fn(request, packet, None, 0, "Completed", None, None, None, "/", None)
    pending_fig, _, _, _, _ = fn(request, packet, None, 0, "Pending approvals", None, None, None, "/", None)
    assert list(all_fig.data[0].x) == [
        'No Rework', '1 Rework', '2 Reworks', '3+ Reworks', 'Unknown']
    assert all(cell[-1] is not None for row in all_fig.data[0].customdata[:-1] for cell in row)
    assert all(len(row) == 5 for row in all_fig.data[0].z)
    assert sum(all_fig.layout.meta['column_totals']) == pytest.approx(12)
    assert heatmap_hours(complete_fig) == pytest.approx(8)
    assert heatmap_hours(pending_fig) == pytest.approx(4)
    manager.get_batch_rework_ratio_df.assert_not_called()

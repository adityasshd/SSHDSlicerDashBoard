"""Daily and user report use the same saved submission accounting contract."""
import pytest

from slicing_dashboard.reporting.dashboard_reports import (
    day_for_ui, prepare_daily_table, prepare_daily_work_chart_rows, summarize_daily,
)


def report():
    return {"date": "2026-10-10", "metadata": {
        "available": True, "capture_kind": "day_end_reconciliation",
        "day_end_reconciled_at": "2026-10-11T18:00:00+05:30"},
        "rows": [
            {"User": "A", "New Videos (First Time)": 7200,
             "Same-day Rework": 1800, "Old Rework": 3600,
             "Total Duration": 12600, "Total Tasks": 5,
             "New Tasks": 3, "Same-day Rework Tasks": 1,
             "Old Rework Tasks": 1, "RawID": "account-a"},
            {"User": "B", "New Videos (First Time)": 3600,
             "Same-day Rework": 0, "Old Rework": 7200,
             "Total Duration": 10800, "Total Tasks": 4,
             "New Tasks": 2, "Same-day Rework Tasks": 0,
             "Old Rework Tasks": 2, "RawID": "account-b"},
        ]}


def test_daily_kpis_user_totals_table_and_chart_are_identical():
    day = day_for_ui(report(), "2026-10-10")
    total = summarize_daily(day)
    a, b = summarize_daily(day, ["A"]), summarize_daily(day, ["B"])
    assert total["total_seconds"] == 12600
    assert total["new_seconds"] == 10800
    assert total["same_day_rework_seconds"] == 1800
    assert total["old_rework_seconds"] == 10800
    assert total["total_seconds"] == a["total_seconds"] + b["total_seconds"]
    assert total["total_tasks"] == a["total_tasks"] + b["total_tasks"]
    assert total["total_seconds"] == total["new_seconds"] + total["same_day_rework_seconds"]
    table = prepare_daily_table(day, numeric_durations=True)
    assert table[-1]["Total Duration"] * 3600 == pytest.approx(total["total_seconds"])
    assert table[-1]["Old Rework"] * 3600 == pytest.approx(total["old_rework_seconds"])
    chart = prepare_daily_work_chart_rows(day)
    assert chart["Total Work Duration"].sum() == pytest.approx(total["total_seconds"])
    assert chart["Old Rework Duration"].sum() == pytest.approx(total["old_rework_seconds"])


def test_daily_old_rework_is_not_relabelled_as_newly_approved():
    day = day_for_ui(report(), "2026-10-10")
    total = summarize_daily(day)
    assert total["old_rework_seconds"] > 0
    assert total["total_seconds"] < total["new_seconds"] + total["same_day_rework_seconds"] + total["old_rework_seconds"]
    assert total["rework_seconds"] == total["same_day_rework_seconds"]


def test_unknown_daily_capture_is_not_silently_counted_as_zero():
    day = day_for_ui(None, "2026-09-20")
    assert summarize_daily(day)["total_seconds"] is None
    assert prepare_daily_table(day) == []

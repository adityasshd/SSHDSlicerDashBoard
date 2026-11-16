"""Closed-settlement snapshots must be immutable, scoped and source-free."""
from copy import deepcopy

import pytest

from slicing_dashboard.reporting.dashboard_panels import KINDS
from slicing_dashboard.reporting.settlement_snapshots import (
    load_snapshot, make_snapshot, manager_snapshot, period_for_range,
    period_for_selection, save_snapshot,
)


class MemoryCollection:
    def __init__(self):
        self.docs = {}
    def find_one(self, query):
        value = self.docs.get(query["_id"])
        return deepcopy(value) if value else None
    def insert_one(self, doc):
        if doc["_id"] in self.docs:
            raise ValueError("duplicate")
        self.docs[doc["_id"]] = deepcopy(doc)


class MemoryDB(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = MemoryCollection()
        return dict.__getitem__(self, key)


PERIOD = {"start_date": "2026-09-01", "end_date": "2026-09-30", "settled": True}


def sample_panels():
    stamp = "2026-09-30T18:50:00+00:00"  # 1 Oct in India, after closure
    packets = {}
    for kind in KINDS:
        data = ({"all": {"total_approved_duration": 3600},
                 "users": {"Riya": {"total_approved_duration": 3600}}, "funnel": {}}
                if kind == "summary" else
                {"columns": ["User", "Completed Duration"],
                 "records": [{"User": "Riya", "Completed Duration": 3600}]})
        packets[kind] = {"available": True, "data": data, "captured_at": stamp}
    return packets


def sample_trend():
    return {"range_start": PERIOD["start_date"], "range_end": PERIOD["end_date"],
            "history": [], "approvals": {}, "efficiency_history": []}


def test_only_explicit_exact_settled_period_is_frozen():
    periods = [PERIOD, {"start_date": "2026-10-01", "end_date": "2026-10-31", "settled": False}]
    assert period_for_range(periods, "2026-09-01", "2026-09-30")
    assert period_for_range(periods, "2026-10-01", "2026-10-31") is None
    assert period_for_selection(periods, "2026-09-01|2026-09-30")
    assert period_for_selection(periods, "2026-09-01|current") is None
    assert period_for_selection(periods, "2026-09-05|2026-09-30") is None


def test_roundtrip_is_immutable_and_does_not_touch_other_collections():
    db = MemoryDB()
    snapshot = make_snapshot(PERIOD, sample_panels(), sample_trend())
    assert snapshot["coverage"]["safe_to_delete_raw_records"] is False
    assert save_snapshot(db, snapshot) is True
    assert save_snapshot(db, deepcopy(snapshot)) is False
    restored = load_snapshot(db, "2026-09-01", "2026-09-30")
    assert restored == snapshot
    assert set(db) == {"settlement_snapshots"}
    changed = deepcopy(snapshot)
    changed["panels"]["summary"]["data"]["all"]["total_approved_duration"] = 9999
    with pytest.raises(ValueError, match="immutable"):
        save_snapshot(db, changed)


def test_missing_or_stale_panels_cannot_be_frozen():
    panels = sample_panels()
    del panels["rework"]
    with pytest.raises(ValueError, match="rework"):
        make_snapshot(PERIOD, panels, sample_trend())
    panels = sample_panels()
    panels["pending"]["captured_at"] = "2026-11-16T12:00:00+00:00"
    with pytest.raises(ValueError, match="pending"):
        make_snapshot(PERIOD, panels, sample_trend())
    with pytest.raises(ValueError, match="exact settlement"):
        make_snapshot(PERIOD, sample_panels(), {**sample_trend(), "range_start": "2026-09-15"})


def test_unsettled_or_incomplete_snapshot_fails_closed():
    with pytest.raises(ValueError, match="settled"):
        make_snapshot({**PERIOD, "settled": False}, sample_panels(), sample_trend())
    db = MemoryDB()
    assert load_snapshot(db, "2026-09-01", "2026-09-30") is None
    snapshot = make_snapshot(PERIOD, sample_panels(), sample_trend())
    save_snapshot(db, snapshot)
    db["settlement_snapshots"].docs["2026-09-01|2026-09-30"]["sha256"] = "bad"
    with pytest.raises(ValueError, match="damaged|checksum"):
        load_snapshot(db, "2026-09-01", "2026-09-30")


def test_manager_read_never_contacts_collector():
    from unittest.mock import MagicMock
    db = MemoryDB()
    save_snapshot(db, make_snapshot(PERIOD, sample_panels(), sample_trend()))
    manager = MagicMock()
    manager.get_available_periods.return_value = [PERIOD]
    manager.db.mongo_db = db
    assert manager_snapshot(manager, *("2026-09-01", "2026-09-30"))["coverage"]["dashboard"]
    manager.scraper.request.assert_not_called()
    manager.get_dashboard_trend_data.assert_not_called()

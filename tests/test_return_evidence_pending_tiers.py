"""Prevent proven 1st/2nd returns falling into Unknown because of partial queues."""
from types import SimpleNamespace

import pytest

from slicing_dashboard.reporting.verified_duration_heatmaps import (
    _fresh_batch_evidence, _return_tiers, pending_duration_rows,
)


class Manager:
    _batches_master_cache = {}
    _batch_returns_cache = []
    _returns_source_error = None
    _batch_source_error = None
    db = None

    @staticmethod
    def _get_reporting_name(uid, username):
        return "Priya"


def row(bid, uid, status, count, duration, returns, *, benchmark=0):
    return {
        "batch_id": bid, "assignee_id": uid, "status": status,
        "production_task_count": count, "total_duration_seconds": duration,
        "benchmark_count": benchmark, "return_count": returns,
    }


def event(bid, uid, legacy, when):
    return {
        "batch_id": bid, "user_id": uid, "legacy_batch_number": legacy,
        "returned_at": when,
        "event_id": f"{uid}_{bid}_{when}",
    }


def task(uid, legacy, task_id, duration, stage="slice_pending_auditor_review",
         *, stable=None):
    return {
        "id": task_id, "slicer_id": uid, "slicer": "SSHD-Priya",
        "status": stage, "slice_batch": legacy,
        "assignment_batch_id": stable, "duration_seconds": duration,
        "is_benchmark_clone": False,
    }


def split(manager, batches, returns, tasks):
    tiers = _return_tiers(batches, returns)
    return pending_duration_rows(manager, batches, tiers, tasks, returns=returns)["Priya"]


def test_priya_9640_first_return_partial_24_of_25_is_identified():
    """Old strict count/duration rule incorrectly put this verified return Unknown."""
    bid = "ab_b7b886515a754267a266850cb82034e7"
    batches = [row(bid, 9640, "batch_pending_auditor_review", 25, 3627, 1)]
    returns = [event(bid, 9640, 12, "2026-11-19T14:57:21")]
    tasks = [task(9640, 12, f"p{i}", 149) for i in range(24)]
    assert sum(x["duration_seconds"] for x in tasks) == 3576
    result = split(Manager(), batches, returns, tasks)
    assert result["1 Rework"] == 3576
    assert result["Unknown"] == 0


def test_priya_18624_second_return_legacy_one_reused_for_october_and_november():
    old = "ab_8bd6fd19dd894b4f8536fb90b28ef91f"
    active = "ab_a3ea66ca3bf9483e86882e3ff58a6900"
    batches = [
        row(old, 18624, "batch_unassigned", 0, 0, 2),
        row(active, 18624, "batch_pending_auditor_review", 34, 3629, 2),
    ]
    returns = [
        event(old, 18624, 1, "2026-10-13T02:22:04"),
        event(old, 18624, 1, "2026-10-21T18:00:01"),
        event(active, 18624, 1, "2026-11-18T16:02:55"),
        event(active, 18624, 1, "2026-11-19T09:27:46"),
    ]
    tasks = [task(18624, 1, f"s{i}", 109) for i in range(32)]
    tasks.append(task(18624, 1, "s32", 113))
    assert sum(x["duration_seconds"] for x in tasks) == 3601
    result = split(Manager(), batches, returns, tasks)
    assert result["2 Reworks"] == 3601
    assert result["Unknown"] == 0


def test_priya_4806_batch_40_new_first_return_is_not_stale_zero_tier():
    bid = "ab_f029210b9eb2453c99ee73a6702fa9fa"
    batches = [row(bid, 4806, "batch_pending_auditor_review", 34, 3836, 1)]
    returns = [event(bid, 4806, 40, "2026-11-19T13:08:58")]
    tasks = [task(4806, 40, f"r{i}", 112) for i in range(33)]
    tasks.append(task(4806, 40, "r33", 140))
    assert sum(t["duration_seconds"] for t in tasks) == 3836
    result = split(Manager(), batches, returns, tasks)
    assert result["1 Rework"] == 3836


def test_priya_6740_first_return_new_batch_under_review():
    bid = "ab_3dffd111e9814cf39aae1877fcecbe1e"
    batches = [row(bid, 6740, "batch_pending_auditor_review", 22, 3793, 1)]
    returns = [event(bid, 6740, 6, "2026-11-19T18:22:00")]
    tasks = [task(6740, 6, f"x{i}", 172) for i in range(21)]
    tasks.append(task(6740, 6, "x21", 181))
    assert sum(t["duration_seconds"] for t in tasks) == 3793
    result = split(Manager(), batches, returns, tasks)
    assert result["1 Rework"] == 3793


def test_legacy_number_collision_between_two_active_batches_remains_unknown():
    a, b = "a", "b"
    batches = [row(a, 18624, "batch_pending_auditor_review", 34, 3629, 1),
               row(b, 18624, "batch_pending_auditor_review", 34, 3629, 1)]
    returns = [event(a, 18624, 1, "2026-11-17T12:00:00"),
               event(b, 18624, 1, "2026-11-18T12:00:00")]
    tasks = [task(18624, 1, f"x{i}", 100) for i in range(33)]
    result = split(Manager(), batches, returns, tasks)
    assert result["Unknown"] == 3300
    assert result["1 Rework"] == 0


def test_partial_group_without_a_return_link_stays_unknown():
    batches = [row("a", 9640, "batch_pending_auditor_review", 25, 3627, 0)]
    tasks = [task(9640, 12, "p", 500)]
    result = split(Manager(), batches, [], tasks)
    assert result["Unknown"] == 500
    assert result["No Rework"] == 0


def test_status_incompatibility_stays_unknown_even_with_recorded_return():
    batches = [row("a", 9640, "batch_pending_auditor_review", 25, 3627, 1)]
    events = [event("a", 9640, 12, "2026-11-19T14:57:21")]
    tasks = [task(9640, 12, "p", 200, stage="slice_pending_admin_review")]
    result = split(Manager(), batches, events, tasks)
    assert result["Unknown"] == 200


def test_cross_stage_over_capacity_reverts_all_linked_cohorts_to_unknown():
    batches = [row("a", 9640, "batch_reviewing", 4, 400, 1)]
    returns = [event("a", 9640, 12, "2026-11-19T12:00:00")]
    tasks = [
        task(9640, 12, "a1", 90, stage="slice_submitted"),
        task(9640, 12, "a2", 90, stage="slice_submitted"),
        task(9640, 12, "a3", 90, stage="slice_submitted"),
        task(9640, 12, "b1", 90, stage="slice_pending_auditor_review"),
        task(9640, 12, "b2", 90, stage="slice_pending_auditor_review"),
        task(9640, 12, "b3", 90, stage="slice_pending_auditor_review"),
    ]
    result = split(Manager(), batches, returns, tasks)
    assert result["Unknown"] == 540
    assert result["1 Rework"] == 0


def test_stable_task_batch_id_can_link_partial_zero_return_batch():
    batches = [row("stable", 9640, "batch_pending_auditor_review", 25, 3627, 0)]
    tasks = [task(9640, None, "p", 200, stable="stable")]
    result = split(Manager(), batches, [], tasks)
    assert result["No Rework"] == 200


def test_bad_owner_or_benchmark_batch_cannot_link_partial_tasks():
    batches = [row("other", 9999, "batch_pending_auditor_review", 5, 600, 1),
               row("benchmark", 9640, "batch_pending_auditor_review", 5, 600, 1,
                   benchmark=1)]
    returns = [event("other", 9999, 1, "2026-11-19T12:00:00"),
               event("benchmark", 9640, 2, "2026-11-19T12:02:00")]
    tasks = [task(9640, 1, "p1", 100), task(9640, 2, "p2", 100)]
    result = split(Manager(), batches, returns, tasks)
    assert result["Unknown"] == 200


def test_mongo_ledgers_refresh_stale_cache_before_tier_calculation():
    new = row("a", 4806, "batch_pending_auditor_review", 34, 3836, 1)
    fresh = [event("a", 4806, 40, "2026-11-19T13:08:58")]
    class Collection:
        def __init__(self, data):
            self.data = data
        def find(self, criteria, projection):
            assert criteria == {}
            assert projection["_id"] == 0
            return list(self.data)

    mongo = SimpleNamespace(name="slicing_dashboard")
    class MockDatabase:
        name = "slicing_dashboard"
        def __getitem__(self, name):
            return {"batches_master": Collection([new]),
                    "batch_returns": Collection(fresh)}[name]
    manager = Manager()
    manager.db = SimpleNamespace(mongo_db=MockDatabase())
    manager._batches_master_cache = {"a": {**new, "return_count": 0}}
    manager._batch_returns_cache = []
    batches, returns, healthy = _fresh_batch_evidence(manager)
    assert healthy is True
    assert _return_tiers(batches, returns)["a"] == "1 Rework"


def test_mongo_read_error_never_pretends_startup_cache_is_fresh():
    class BrokenDB:
        name = "slicing_dashboard"
        def __getitem__(self, name):
            raise RuntimeError("connection failed")
    manager = Manager()
    manager.db = SimpleNamespace(mongo_db=BrokenDB())
    manager._batches_master_cache = {"a": row(
        "a", 4806, "batch_pending_auditor_review", 34, 3836, 0)}
    batches, returns, healthy = _fresh_batch_evidence(manager)
    assert healthy is False
    assert _return_tiers(batches, returns, healthy) == {}

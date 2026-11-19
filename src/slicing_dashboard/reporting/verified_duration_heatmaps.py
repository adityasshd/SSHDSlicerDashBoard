"""Evidence-first VIDEO DURATION splits for the two rework heatmap views.

Completed: source-dated efficiency hours; reconcile to archived batch observations.
Pending: currently queued leader/auditor/admin task hours, never whole-batch
duration unless the entire current task cohort uniquely matches one batch.
Return tiers are OBSERVED LIFETIME batch events, not rework labor or the
return count before a particular completion. Anything ambiguous is Unknown.
"""
from collections import defaultdict
from datetime import date, timedelta
from itertools import combinations
from math import isfinite
import json
import logging

import pandas as pd

from slicing_dashboard.processing.batch_return_history import occurrence_identity
from slicing_dashboard.processing.daily_work import instant

log = logging.getLogger(__name__)

TIERS = ("No Rework", "1 Rework", "2 Reworks", "3+ Reworks", "Unknown")
STAGES = {
    "slice_submitted": "Pending Leader",
    "slice_pending_auditor_review": "Pending Auditor",
    "slice_pending_admin_review": "Pending Admin",
}
BATCH_STAGES = {
    "Pending Leader": {"batch_member_assigned", "batch_reviewing"},
    "Pending Auditor": {"batch_pending_auditor_review", "batch_reviewing"},
    "Pending Admin": {"batch_pending_admin_review"},
}
TOLERANCE_SECONDS = 0.5
EXCLUDED = {"admin", "test", "dep", "exempt", "user-none", "(unassigned)", "unassigned", ""}


class EfficiencyCaptureUnavailable(ValueError):
    """Missing dated archive coverage is a source problem, never zero hours."""


def historical_store_unavailable(manager):
    """Detect a failed configured remote database before local SQLite fallback.

    An intentional SQLite-only installation may legitimately have local
    history. A configured Atlas/Postgres connection that failed during startup
    must NOT be silently replaced by an unrelated local empty history.
    """
    db = getattr(manager, "db", None)
    if db is None:
        return False
    settings = getattr(db, "settings", None)
    uri = (getattr(settings, "mongo_uri", None) or
           getattr(settings, "database_url", None) or "")
    configured_remote = str(uri).startswith(("mongodb://", "mongodb+srv://",
                                             "postgres://", "postgresql://"))
    return bool(configured_remote and getattr(db, "mongo_db", None) is None and
                getattr(db, "engine", None) is None)


def seconds(value):
    if value is None or isinstance(value, bool):
        raise ValueError("Video duration missing")
    result = float(value)
    if not isfinite(result) or result < 0:
        raise ValueError("Invalid video duration")
    return result


def integer(value):
    if value is None or isinstance(value, bool):
        raise ValueError("Missing production task count")
    result = int(value)
    if result < 0 or float(value) != result:
        raise ValueError("Invalid production task count")
    return result


def _name(manager, uid, username):
    user = manager._get_reporting_name(uid, username)
    return user if user and str(user).casefold() not in EXCLUDED else None


def _return_tiers(batches, returns, source_healthy=True):
    """Only classify verified complete observed return counts by stable ID."""
    seen = defaultdict(set)
    bad = set()
    for event in returns:
        bid = str(event.get("batch_id") or "")
        if not bid:
            continue
        try:
            stamp = instant(event.get("returned_at"))
            if stamp is None:
                raise ValueError("Missing timestamp")
            seen[bid].add(occurrence_identity(event, stamp))
        except (ValueError, TypeError, OverflowError):
            bad.add(bid)
    tiers = {}
    for row in batches:
        bid = row.get("batch_id")
        if not bid:
            continue
        try:
            ledger = integer(row["return_count"])
            if not source_healthy or bid in bad or ledger != len(seen[bid]):
                continue
            tiers[bid] = TIERS[min(3, ledger)]
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return tiers


def _archive_states(store, start, end):
    """Read only normalized distinct states for the requested observation window.

    In MongoDB, perform the 47k-document payload extraction and grouping on
    the server. Transfer the small set of distinct numeric states, not the
    entire archival observation history, to Vercel.
    """
    if store.mongo is None:
        rows = store.records("batch-observation")
        parsed = []
        for row in rows:
            stamp = str(row.get("observed_at") or "")
            if start <= stamp[:10] <= end:
                batch = row.get("batch") or {}
                parsed.append({
                    "bid": batch.get("batch_id"), "uid": str(batch.get("assignee_id")),
                    "count": batch.get("production_task_count"),
                    "value": batch.get("total_duration_seconds"),
                    "bench": batch.get("benchmark_count"),
                    "completed": batch.get("completed_count"),
                    "status": batch.get("status"),
                })
    else:
        patterns = {
            "bid": r'"batch_id":"(ab_[0-9a-f]+)"',
            "uid": r'"assignee_id":([0-9]+)',
            "count": r'"production_task_count":([0-9]+)',
            "value": r'"total_duration_seconds":([0-9.eE+-]+)',
            "bench": r'"benchmark_count":([0-9]+)',
            "completed": r'"completed_count":([0-9]+)',
            "status": r'"status":"([^"]+)"',
            "observed": r'"observed_at":"([^"]+)"',
        }
        matches = {"m_" + k: {"$regexFind": {"input": "$payload", "regex": v}}
                   for k, v in patterns.items()}
        field = lambda key: {"$arrayElemAt": ["$m_" + key + ".captures", 0]}
        projections = {key: field(key) for key in patterns}
        following = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        # Most snapshots predate the requested period. Match month prefixes
        # before running eight regex extractions on large archived payloads.
        # This filter narrows scanning but the exact day range below remains
        # authoritative (including ranges spanning multiple months).
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
        months = set()
        cursor = first
        while cursor <= last:
            months.add(cursor.strftime("%Y-%m"))
            cursor += timedelta(days=1)
        month_prefix = r'"observed_at":"(?:' + '|'.join(sorted(months)) + r')-'
        pipeline = [
            {"$match": {"kind": "batch-observation",
                        "payload": {"$regex": month_prefix}}},
            {"$project": matches},
            {"$project": projections},
            {"$match": {"observed": {"$gte": start, "$lt": following},
                        "bid": {"$ne": None}, "uid": {"$ne": None}}},
            {"$group": {
                "_id": {"bid": "$bid", "uid": "$uid", "count": "$count",
                        "value": "$value", "bench": "$bench"},
                "completedPeak": {"$max": {"$toInt": "$completed"}},
                "statuses": {"$addToSet": "$status"},
            }},
            {"$project": {"_id": 0, "bid": "$_id.bid", "uid": "$_id.uid",
                          "count": "$_id.count", "value": "$_id.value",
                          "bench": "$_id.bench", "completedPeak": 1,
                          "statuses": 1}},
        ]
        return list(store.mongo["workflow_records"].aggregate(
            pipeline, allowDiskUse=True, maxTimeMS=30000))
    grouped = {}
    for row in parsed:
        try:
            key = (row["bid"], row["uid"], integer(row["count"]),
                   seconds(row["value"]), integer(row["bench"]))
            if not key[0] or not key[1]:
                continue
            target = grouped.setdefault(key, {"bid": key[0], "uid": key[1],
                "count": key[2], "value": key[3], "bench": key[4],
                "completedPeak": 0, "statuses": set()})
            target["completedPeak"] = max(target["completedPeak"],
                                          integer(row["completed"]))
            target["statuses"].add(row["status"])
        except (ValueError, TypeError, KeyError):
            continue
    return [{**row, "statuses": list(row["statuses"])} for row in grouped.values()]


def _candidate_options(states):
    """Create unique completed-batch production durations from archived states."""
    groups = defaultdict(list)
    for raw in states:
        try:
            row = {"bid": str(raw["bid"]), "uid": str(raw["uid"]),
                   "count": integer(raw["count"]), "value": seconds(raw["value"]),
                   "bench": integer(raw["bench"]),
                   "completed": integer(raw["completedPeak"]),
                   "statuses": set(raw["statuses"])}
        except (KeyError, ValueError, TypeError):
            continue
        if row["bid"] and row["uid"]:
            groups[(row["uid"], row["bid"], row["count"])].append(row)
    options = defaultdict(list)
    for (uid, bid, count), states_for_batch in groups.items():
        if not any("batch_completed" in row["statuses"] for row in states_for_batch):
            continue
        by_value = {}
        for row in states_for_batch:
            if row["bench"] == 0 and row["value"] > 0:
                by_value[round(row["value"], 6)] = {
                    "bid": bid, "count": count, "seconds": row["value"], "method": "direct"}
        for high in states_for_batch:
            if high["bench"] < 1 or high["completed"] < count:
                continue
            for low in states_for_batch:
                if (low["bench"] < 1 or low["completed"] > 1 or
                        not 0 < low["value"] <= 300 or high["value"] <= low["value"]):
                    continue
                amount = high["value"] - low["value"]
                by_value[round(amount, 6)] = {
                    "bid": bid, "count": count, "seconds": amount,
                    "method": "benchmark-residual"}
        options[uid].extend(by_value.values())
    return options


def _match_account_day(uid, count, total, options):
    """Unique one-, two- or three-batch numeric decomposition, else Unknown."""
    eligible = [row for row in options.get(uid, [])
                if row["count"] <= count and row["seconds"] <= total + TOLERANCE_SECONDS]
    for size in (1, 2, 3):
        found = {}
        for combination in combinations(eligible, size):
            if len({item["bid"] for item in combination}) != size:
                continue
            if sum(item["count"] for item in combination) != count:
                continue
            if abs(sum(item["seconds"] for item in combination) - total) > TOLERANCE_SECONDS:
                continue
            key = tuple(sorted(item["bid"] for item in combination))
            found.setdefault(key, list(combination))
        # Any multiple possible decompositions of the same cardinality are
        # ambiguous; never take the first one. A unique single batch dominates
        # multi-batch guesses; that hierarchy mirrors the audited workbook.
        if found:
            return next(iter(found.values())) if len(found) == 1 else None
    return None


def _efficiency_days(store, start, end):
    captures = store.records("efficiency-capture", start=start, end=end)
    selected = {}
    for row in captures:
        day = str(row.get("display_date") or row.get("date") or "")
        if not start <= day <= end or not isinstance(row.get("items"), list):
            continue
        if day not in selected or str(row.get("captured_at", "")) > str(selected[day].get("captured_at", "")):
            selected[day] = row
    return selected


def completed_duration_rows(manager, start, end, store, tiers):
    captures = _efficiency_days(store, start, end)
    expected = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if expected < 1 or expected > 62:
        raise EfficiencyCaptureUnavailable(
            "Selected range exceeds supported historical capture window")
    if len(captures) != expected:
        raise EfficiencyCaptureUnavailable(
            f"Historical efficiency days missing: {expected - len(captures)} "
            f"of {expected} for {start} through {end}")
    options = _candidate_options(_archive_states(store, start, end))
    by_user = defaultdict(lambda: dict.fromkeys(TIERS, 0.0))
    for day in sorted(captures):
        for item in captures[day]["items"]:
            count = integer(item.get("completed_count", 0))
            duration = seconds(item.get("completed_duration_seconds", 0))
            if not duration:
                continue
            name = _name(manager, item.get("user_id"), item.get("username"))
            if not name:
                continue
            uid = str(item.get("user_id"))
            selection = _match_account_day(uid, count, duration, options)
            if selection and all(part["bid"] in tiers for part in selection):
                difference = duration - sum(p["seconds"] for p in selection)
                for index, part in enumerate(selection):
                    by_user[name][tiers[part["bid"]]] += part["seconds"] + (
                        difference if index == 0 else 0)
            else:
                by_user[name]["Unknown"] += duration
    return by_user



def _fresh_batch_evidence(manager):
    """Use latest *persisted* batch and return ledgers when MongoDB is available.

    The live review queue is independently fetched. Mixing it with startup
    ledger caches misclassifies recent returns as zero or Unknown. Read the
    two small indexed ledgers together; fail closed if either query fails.
    No expensive upstream per-account request or task-video scan is added.
    """
    cache = getattr(manager, "_batches_master_cache", {}) or {}
    batches = list(cache.values()) if isinstance(cache, dict) else list(cache)
    returns = getattr(manager, "_batch_returns_cache", []) or []
    returns = list(returns.values()) if isinstance(returns, dict) else list(returns)
    healthy = not (getattr(manager, "_returns_source_error", None) or
                   getattr(manager, "_batch_source_error", None))
    db = getattr(manager, "db", None)
    mongo = getattr(db, "mongo_db", None)
    # In unit tests a MagicMock may expose arbitrary attributes including
    # .mongo_db. Real pymongo Database.name is a literal string.
    if mongo is None or not isinstance(getattr(mongo, "name", None), str):
        return batches, returns, healthy
    fields = {"_id": 0, "batch_id": 1, "assignee_id": 1, "status": 1,
              "batch_date": 1, "return_count": 1,
              "production_task_count": 1, "benchmark_count": 1,
              "total_duration_seconds": 1}
    event_fields = {"_id": 0, "batch_id": 1, "event_id": 1,
                    "user_id": 1, "legacy_batch_number": 1,
                    "returned_at": 1}
    try:
        latest_batches = list(mongo["batches_master"].find({}, fields))
        latest_returns = list(mongo["batch_returns"].find({}, event_fields))
        if not latest_batches:
            raise ValueError("Empty persisted batch ledger")
        return latest_batches, latest_returns, True
    except Exception:
        log.exception("Persisted batch/return evidence unavailable")
        return batches, returns, False


def _legacy_return_links(returns):
    """Return IDs prove (operator, legacy number) -> permanent batch candidates.

    A legacy number is reusable. Do not resolve collisions here; the current
    ledger must reduce candidates to exactly one same-owner, compatible-stage
    batch before linking any of its current task video seconds.
    """
    links = defaultdict(set)
    for event in returns:
        bid = str(event.get("batch_id") or "")
        uid = event.get("user_id")
        legacy = event.get("legacy_batch_number")
        if not bid or uid is None or legacy is None or isinstance(legacy, bool):
            continue
        links[(str(uid), str(legacy))].add(bid)
    return links


def _batch_can_contain(batch, uid, stage, count, duration, *, partial):
    if (str(batch.get("assignee_id")) != uid or
            batch.get("status") not in BATCH_STAGES[stage]):
        return False
    try:
        task_count = integer(batch.get("production_task_count"))
        total = seconds(batch.get("total_duration_seconds"))
        benchmark = integer(batch.get("benchmark_count", 0))
    except (ValueError, TypeError, OverflowError):
        return False
    if benchmark != 0:
        # Don't attribute the production portion without excluding benchmarks
        # by task identity from both sides of the comparison.
        return False
    if partial:
        return (0 < count <= task_count and
                0 < duration <= total + TOLERANCE_SECONDS)
    return count == task_count and abs(total - duration) <= TOLERANCE_SECONDS


def pending_duration_rows(manager, batches, tiers, task_records, returns=None):
    """Classify live task VIDEO seconds only with unique evidence-backed joins.

    Priority: task's permanent batch ID; a uniquely compatible batch backed
    by a return event's (user_id, legacy_batch_number, batch_id); or an
    exact full-batch numeric match. A partially visible queue is admissible
    only with the first two stronger forms of identity. All unmatched or
    over-attributed task seconds remain Unknown.
    """
    cohorts = defaultdict(list)
    all_ids = set()
    for task in task_records:
        status = task.get("status")
        if status not in STAGES:
            raise ValueError("Unexpected pending task status")
        ident = str(task.get("id") or task.get("task_id") or "")
        if not ident or ident in all_ids:
            raise ValueError("Missing or repeated pending task")
        all_ids.add(ident)
        if task.get("is_benchmark_clone") is True:
            continue
        uid = str(task.get("slicer_id"))
        user = _name(manager, task.get("slicer_id"), task.get("slicer"))
        if not user:
            continue
        stable = task.get("assignment_batch_id") or task.get("batch_id")
        legacy = task.get("slice_batch")
        group = (user, uid, STAGES[status],
                 "stable:" + str(stable) if stable else "legacy:" + str(legacy))
        cohorts[group].append(task)

    by_id = {row["batch_id"]: row for row in batches if row.get("batch_id")}
    legacy_links = _legacy_return_links(returns or [])
    assignments = []
    for (user, uid, stage, key), tasks in cohorts.items():
        duration = sum(seconds(task.get("duration_seconds")) for task in tasks)
        if not duration:
            continue
        count = len(tasks)
        selected = None
        if key.startswith("stable:"):
            bid = key[7:]
            batch = by_id.get(bid)
            if (bid in tiers and batch is not None and
                    _batch_can_contain(batch, uid, stage, count, duration, partial=True)):
                selected = bid
        else:
            # The return-history event directly relates this operator's
            # displayed legacy batch number to one or more permanent IDs.
            # Reuse can occur; require one viable CURRENT active batch.
            candidates = [
                bid for bid in legacy_links.get((uid, key[7:]), set())
                if bid in tiers and bid in by_id and
                _batch_can_contain(by_id[bid], uid, stage, count, duration, partial=True)
            ]
            if len(candidates) == 1:
                selected = candidates[0]
            elif len(candidates) == 0:
                # Preserve the old conservative whole-cohort matching for
                # zero-return batches that have no return event to link them.
                exact = [
                    bid for bid, batch in by_id.items()
                    if bid in tiers and
                    _batch_can_contain(batch, uid, stage, count, duration, partial=False)
                ]
                if len(exact) == 1:
                    selected = exact[0]
            # More than one current viable candidate remains Unknown.
        assignments.append((user, count, duration, selected))

    attributed = defaultdict(lambda: [0, 0.0])
    for _, count, duration, bid in assignments:
        if bid is not None:
            attributed[bid][0] += count
            attributed[bid][1] += duration

    # Cross-stage protection: if multiple queue cohorts unexpectedly link to
    # the same permanent batch but collectively exceed the batch's production
    # count or video duration, attribute NONE of those cohorts to that tier.
    excessive = set()
    for bid, (count, duration) in attributed.items():
        batch = by_id[bid]
        if (count > integer(batch["production_task_count"]) or
                duration > seconds(batch["total_duration_seconds"]) + TOLERANCE_SECONDS):
            excessive.add(bid)

    by_user = defaultdict(lambda: dict.fromkeys(TIERS, 0.0))
    for user, _, duration, bid in assignments:
        tier = tiers[bid] if bid is not None and bid not in excessive else "Unknown"
        by_user[user][tier] += duration
    return by_user


def _state_rows(split, state):
    for user, amounts in sorted(split.items()):
        total = sum(amounts.values())
        yield {"User": user, "Completion State": state, "Total Batches": 0,
               "No Rework": 0, "1 Rework": 0, "2 Reworks": 0,
               "3+ Reworks": 0, "Unknown": 0, "3+ Return Count": 0,
               "Verified Tier Duration (hrs)": {
                   name: seconds / 3600 for name, seconds in amounts.items()},
               "Verified Total Seconds": total,
               "Verified Hours Available": True}


def with_verified_duration(manager, ratio_frame, start, end):
    """Attach independent duration evidence; keep original batch counts intact."""
    from slicing_dashboard.processing.pending_review import capture_for
    from slicing_dashboard.processing.workflow_history import WorkflowStore
    store = WorkflowStore(getattr(manager, "db", None), initialize=False).chart_reader()
    batches, returns, healthy = _fresh_batch_evidence(manager)
    tiers = _return_tiers(batches, returns, healthy)
    # Independent source failures must not hide another verified duration
    # source. Completed fallback uses the separate source-date completion
    # panel as Unknown; Pending never falls back to whole-batch inventory.
    failures = []
    # If the configured Atlas/PG store failed to initialize (e.g. SRV DNS
    # timeout), a local SQLite file may exist but is NOT the same dataset.
    # Retain independently verified live pending video durations, while
    # marking completed archive coverage explicitly unavailable.
    if historical_store_unavailable(manager):
        completed = {}
        failures.append("Completed archive: configured database unavailable")
        log.warning("Verified completed duration unavailable: configured "
                    "historical database did not initialize")
    else:
        try:
            completed = completed_duration_rows(manager, start, end, store, tiers)
        except EfficiencyCaptureUnavailable as error:
            completed = {}
            failures.append("Completed archive: incomplete daily coverage")
            log.warning("Verified completed duration unavailable: %s", error)
        except Exception as error:
            log.exception('Verified completed duration reconstruction failed')
            completed = {}
            failures.append("Completed archive: " + type(error).__name__)
    try:
        capture = capture_for(manager).read(manager.scraper)
        if capture.get("error") or "tasks" not in capture:
            raise ValueError("Live pending task queue unavailable")
        pending = pending_duration_rows(manager, batches, tiers, capture["tasks"], returns=returns)
    except Exception as error:
        log.exception('Verified pending queue duration reconstruction failed')
        pending = {}
        failures.append("Pending task queue: " + type(error).__name__)
    additions = list(_state_rows(completed, "Completed")) + list(_state_rows(pending, "Pending approvals"))
    fields = ["Verified Tier Duration (hrs)", "Verified Total Seconds", "Verified Hours Available", "Verified Source Warning"]
    frame = ratio_frame.copy()
    for key in fields:
        frame[key] = None
    frame["Verified Source Warning"] = "; ".join(failures)
    existing = {(row["User"], row["Completion State"]): index for index, row in frame.iterrows()}
    new_rows = []
    for row in additions:
        key = (row["User"], row["Completion State"])
        if key in existing:
            index = existing[key]
            for field in fields:
                frame.at[index, field] = row[field]
        else:
            new_rows.append(row)
    if new_rows:
        extra = pd.DataFrame(new_rows)
        extra["Verified Source Warning"] = "; ".join(failures)
        frame = pd.concat([frame, extra], ignore_index=True)
    # Explicit unavailability, not zero, for missing known user/state cells.
    # Preserve a source warning even when there are no user rows to serialize.
    frame.attrs["source_warnings"] = list(failures)
    return frame

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

import pandas as pd

from slicing_dashboard.processing.batch_return_history import occurrence_identity
from slicing_dashboard.processing.daily_work import instant

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
    if expected < 1 or expected > 62 or len(captures) != expected:
        raise ValueError("Incomplete source-dated efficiency capture for selected range")
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


def pending_duration_rows(manager, batches, tiers, task_records):
    """Classify only full, unique queue-group matches; partial batches Unknown."""
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
        key = (user, uid, STAGES[status],
               "stable:" + str(stable) if stable else "legacy:" + str(legacy))
        cohorts[key].append(task)
    by_user = defaultdict(lambda: dict.fromkeys(TIERS, 0.0))
    for (user, uid, stage, key), tasks in cohorts.items():
        value = sum(seconds(task.get("duration_seconds")) for task in tasks)
        if not value:
            continue
        count = len(tasks)
        matches = []
        for batch in batches:
            if str(batch.get("assignee_id")) != uid or batch.get("status") not in BATCH_STAGES[stage]:
                continue
            bid = batch.get("batch_id")
            if key.startswith("stable:") and key[7:] != str(bid):
                continue
            try:
                valid = (integer(batch.get("production_task_count", 0)) == count and
                         abs(seconds(batch.get("total_duration_seconds", 0)) - value) <= TOLERANCE_SECONDS and
                         integer(batch.get("benchmark_count", 0)) == 0)
            except (ValueError, TypeError, OverflowError):
                valid = False
            if valid:
                matches.append(bid)
        # A legacy number is not a stable ID. Require full cohort, same owner,
        # same stage, unique count+duration, and a verified return ledger.
        if len(matches) == 1 and matches[0] in tiers:
            by_user[user][tiers[matches[0]]] += value
        else:
            by_user[user]["Unknown"] += value
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
    batches = list(getattr(manager, "_batches_master_cache", {}).values())
    returns = getattr(manager, "_batch_returns_cache", []) or []
    if isinstance(returns, dict):
        returns = list(returns.values())
    healthy = not (getattr(manager, "_returns_source_error", None) or
                   getattr(manager, "_batch_source_error", None))
    tiers = _return_tiers(batches, returns, healthy)
    # Independent source failures must not hide another verified duration
    # source. Completed fallback uses the separate source-date completion
    # panel as Unknown; Pending never falls back to whole-batch inventory.
    failures = []
    try:
        completed = completed_duration_rows(manager, start, end, store, tiers)
    except Exception as error:
        completed = {}
        failures.append("Completed archive: " + type(error).__name__)
    try:
        capture = capture_for(manager).read(manager.scraper)
        if capture.get("error") or "tasks" not in capture:
            raise ValueError("Live pending task queue unavailable")
        pending = pending_duration_rows(manager, batches, tiers, capture["tasks"])
    except Exception as error:
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
    return frame

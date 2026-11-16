"""Immutable, compact settlement dashboard snapshots.

A settled period is rendered from an independently persisted dashboard capture,
never from the rotating `dashboard_snapshot` cache or a live source read.
Archival/deletion is intentionally NOT part of this module.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import zlib
from zoneinfo import ZoneInfo

from slicing_dashboard.reporting.dashboard_panels import KINDS

SCHEMA_VERSION = 1
COLLECTION = "settlement_snapshots"
ENCODING = "zlib-base64-v1"
MAX_COMPRESSED_BYTES = 12 * 1024 * 1024
_INDIA = ZoneInfo("Asia/Kolkata")


def period_for_range(periods, start: str, end: str):
    """Return a truly settled, exact period; prior calendar months are not enough."""
    for period in periods:
        if (period.get("settled") is True and period.get("start_date") == start
                and period.get("end_date") == end):
            return dict(period)
    return None


def period_for_selection(periods, value):
    """Only the settlement dropdown's explicit closed-period value is frozen."""
    if not isinstance(value, str) or "|" not in value:
        return None
    start, end = value.split("|", 1)
    return period_for_range(periods, start, end)


def snapshot_id(start: str, end: str):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("Settlement start must precede its end")
    return f"{first.isoformat()}|{last.isoformat()}"


def _encoded(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _captured_near_closure(packet: dict, end: str) -> bool:
    """Prevent today's assigned/pending state being labelled a months-old close."""
    try:
        stamp = datetime.fromisoformat(packet["captured_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return False
        captured_day = stamp.astimezone(_INDIA).date()
        closed_day = date.fromisoformat(end)
        return closed_day <= captured_day <= closed_day + timedelta(days=1)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def make_snapshot(period: dict, panels: dict, trend: dict, *,
                  user_reports: dict | None = None) -> dict:
    """Prepare a dashboard-only snapshot with strict, non-fabricated coverage.

    No write is made. In particular, a settlement cannot be retroactively
    frozen from the present-day pending/assigned queue. User Reports are
    optional and explicitly marked as *not* covered by the archival gate.
    """
    start, end = period.get("start_date"), period.get("end_date")
    if not start or not end or period.get("settled") is not True:
        raise ValueError("Only an explicitly settled period may be frozen")
    snapshot_id(start, end)
    missing = [kind for kind in KINDS
               if not isinstance(panels.get(kind), dict)
               or panels[kind].get("available") is not True
               or not isinstance(panels[kind].get("data"), dict)]
    if missing:
        raise ValueError("Missing verified dashboard panels: " + ", ".join(missing))
    for kind in KINDS:
        if not _captured_near_closure(panels[kind], end):
            raise ValueError(f"{kind} panel was not captured at settlement closure")
    if not isinstance(trend, dict) or (trend.get("range_start"), trend.get("range_end")) != (start, end):
        raise ValueError("Trend capture must cover the exact settlement dates")
    if not all(isinstance(trend.get(key), list if key != "approvals" else dict)
               for key in ("history", "approvals", "efficiency_history")):
        raise ValueError("Trend evidence is incomplete")
    for kind in ("completion", "rework", "assigned", "pending"):
        frame = panels[kind]["data"]
        if (not isinstance(frame.get("columns"), list)
                or not isinstance(frame.get("records"), list)):
            raise ValueError(f"{kind} frame is incomplete")
    summary = panels["summary"]["data"]
    if not isinstance(summary.get("all"), dict) or not isinstance(summary.get("users"), dict):
        raise ValueError("Summary per-user aggregates are incomplete")
    return {
        "schema_version": SCHEMA_VERSION,
        "settlement": {"start_date": start, "end_date": end, "settled": True},
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "panels": {key: deepcopy(panels[key]) for key in KINDS},
        "trend": deepcopy(trend),
        "user_reports": deepcopy(user_reports) if user_reports is not None else None,
        "coverage": {"dashboard": True, "individual_reports": user_reports is not None,
                     "daily_drilldown": False, "raw_workflow_history": False,
                     "safe_to_delete_raw_records": False},
    }


def save_snapshot(mongo_db, snapshot: dict):
    """Insert once, never overwrite a closed period or touch raw collections.

    Returns True for a new insert, False for the same frozen payload.
    A different payload at the same period ID is rejected.
    """
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported snapshot schema")
    period = snapshot["settlement"]
    if period.get("settled") is not True or not snapshot.get("coverage", {}).get("dashboard"):
        raise ValueError("Unverified settlement snapshot")
    identifier = snapshot_id(period["start_date"], period["end_date"])
    raw = _encoded(snapshot)
    compressed = zlib.compress(raw, 9)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise ValueError("Settlement snapshot exceeds safe BSON payload size")
    digest = sha256(raw).hexdigest()
    collection = mongo_db[COLLECTION]
    existing = collection.find_one({"_id": identifier})
    if existing is not None:
        if existing.get("sha256") == digest:
            return False
        raise ValueError("An immutable snapshot already exists for this settlement")
    doc = {"_id": identifier, "schema_version": SCHEMA_VERSION,
           "encoding": ENCODING, "sha256": digest,
           "compressed_bytes": len(compressed),
           "snapshot_payload": base64.b64encode(compressed).decode("ascii"),
           "start_date": period["start_date"], "end_date": period["end_date"],
           "frozen_at": snapshot["frozen_at"]}
    try:
        collection.insert_one(doc)
    except Exception as error:
        # A concurrent writer may have won the unique _id constraint.
        if type(error).__name__ != "DuplicateKeyError":
            raise
        winner = collection.find_one({"_id": identifier})
        if winner is None or winner.get("sha256") != digest:
            raise ValueError("Conflicting concurrent settlement snapshot") from error
        return False
    return True


def load_snapshot(mongo_db, start: str, end: str):
    """Read and verify one historical snapshot; no live source fallback."""
    doc = mongo_db[COLLECTION].find_one({"_id": snapshot_id(start, end)})
    if doc is None:
        return None
    if doc.get("schema_version") != SCHEMA_VERSION or doc.get("encoding") != ENCODING:
        raise ValueError("Unsupported settlement snapshot version")
    try:
        raw = zlib.decompress(base64.b64decode(doc["snapshot_payload"], validate=True))
        if sha256(raw).hexdigest() != doc["sha256"]:
            raise ValueError("Settlement snapshot checksum mismatch")
        payload = json.loads(raw)
    except (KeyError, TypeError, ValueError, zlib.error) as error:
        raise ValueError("Settlement snapshot damaged or unreadable") from error
    period = payload.get("settlement", {})
    if period.get("start_date") != start or period.get("end_date") != end:
        raise ValueError("Settlement snapshot period mismatch")
    if not payload.get("coverage", {}).get("dashboard"):
        raise ValueError("Settlement dashboard coverage not verified")
    return payload


def manager_snapshot(manager, start: str, end: str):
    """Read a closed settlement without triggering any upstream collection."""
    period = period_for_range(manager.get_available_periods(), start, end)
    if period is None:
        return None
    mongo = getattr(manager.db, "mongo_db", None)
    if mongo is None:
        return None
    return load_snapshot(mongo, start, end)

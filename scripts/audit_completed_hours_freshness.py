#!/usr/bin/env python3
"""Read-only audit: are latest efficiency captures reaching Completed Hours panels?

Prints ONLY timestamps, availability, and record counts. Never prints users,
videos, token material, secrets, or the saved chart data.
Requires pymongo and MONGO_URI / MONGODB_URI locally.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import json
import os
from pathlib import Path
import sys
import zlib

DB_NAME = "slicing_dashboard"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def snapshot_metadata(document):
    """Extract safe panel capture metadata without exposing dashboard rows."""
    if not isinstance(document, dict):
        raise ValueError("Missing dashboard snapshot")
    if document.get("snapshot_encoding") != "zlib-base64-v1":
        raise ValueError("Expected compressed-v1 snapshot")
    data = base64.b64decode(document["snapshot_payload"], validate=True)
    snapshot = json.loads(zlib.decompress(data).decode("utf-8"))
    if not isinstance(snapshot, dict):
        raise ValueError("Invalid dashboard snapshot body")

    packets = snapshot.get("dashboard_panels", {})
    if not isinstance(packets, dict):
        raise ValueError("Invalid saved panels")
    completion = []
    for key, packet in packets.items():
        if not isinstance(packet, dict):
            continue
        frame = packet.get("data", {})
        columns = frame.get("columns", []) if isinstance(frame, dict) else []
        if not {"User", "Completed Duration", "Completed Tasks"}.issubset(columns):
            continue
        completion.append({
            "panel_id_prefix": str(key)[:10],
            "available": packet.get("available") is True,
            "captured_at": packet.get("captured_at"),
            "user_rows": len(frame.get("records") or []),
        })
    completion.sort(key=lambda x: str(x.get("captured_at") or ""), reverse=True)
    return {"saved_snapshot_updated_at": document.get("updated_at"),
            "total_saved_panels": len(packets),
            "completion_panels": completion}


def compare(latest_source, report):
    """Report an evidence-backed lag without interpreting source-day totals."""
    saved = report["completion_panels"]
    result = {
        "last_efficiency_capture_date": latest_source.get("display_date") if latest_source else None,
        "last_efficiency_capture_at": latest_source.get("sort_at") if latest_source else None,
        "last_snapshot_write_at": report["saved_snapshot_updated_at"],
        "completion_panel_count": len(saved),
        "latest_completion_panel_at": saved[0]["captured_at"] if saved else None,
        "recent_completion_panels": saved[:10],
        "assessment": "unknown",
    }
    if not latest_source:
        result["assessment"] = "no_efficiency_capture"
        return result
    if not saved:
        result["assessment"] = "no_saved_completion_panel"
        return result
    try:
        a = datetime.fromisoformat(str(latest_source["sort_at"]).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(saved[0]["captured_at"]).replace("Z", "+00:00"))
        if a.tzinfo is None or b.tzinfo is None:
            raise ValueError("Missing timezone")
        lag = (a - b).total_seconds()
        result["lag_seconds_at_latest"] = int(lag)
        result["assessment"] = (
            "completion_panel_older_than_efficiency" if lag > 60 else
            "completion_panel_as_new_or_newer_than_efficiency"
        )
    except (ValueError, TypeError, KeyError):
        result["assessment"] = "timestamps_incomplete"
    return result


def settlement_scope_health(current, today):
    """Check whether the current unsettled collector window reaches today."""
    if not isinstance(current, dict):
        return {"state": "no_current_settlement"}
    start = current.get("start_date")
    end = current.get("end_date")
    if not isinstance(start, str) or not isinstance(end, str):
        return {"state": "invalid_settlement_dates"}
    try:
        start_day = date.fromisoformat(start)
        end_day = date.fromisoformat(end)
        now_day = date.fromisoformat(today)
    except ValueError:
        return {"state": "invalid_settlement_dates"}
    if end_day < start_day:
        return {"state": "invalid_settlement_date_order"}
    result = {"start_date": start, "configured_end_date": end,
              "requested_current_day": today, "settled": current.get("settled")}
    if current.get("settled") is False and end_day < now_day:
        result.update(state="open_settlement_ends_before_today",
                      missing_calendar_days=(now_day - end_day).days)
    else:
        result.update(state="date_window_covers_today"
                      if start_day <= now_day <= end_day else "date_window_not_current")
    return result


def run():
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass
    uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")
    if not uri or not uri.startswith(("mongodb://", "mongodb+srv://")):
        raise ValueError("MongoDB URI not configured")
    from pymongo import MongoClient
    with MongoClient(uri, serverSelectionTimeoutMS=10000,
                     appname="SlicerCompletionAudit") as client:
        db = client[DB_NAME]
        doc = db["dashboard_snapshot"].find_one(
            {"_id": "latest-compressed-v1"},
            {"snapshot_payload": 1, "snapshot_encoding": 1, "updated_at": 1})
        metadata = snapshot_metadata(doc)
        latest = db["workflow_records"].find_one(
            {"kind": "efficiency-capture"},
            {"_id": 0, "display_date": 1, "sort_at": 1},
            sort=[("display_date", -1)])
        current = db["settlement_periods"].find_one(
            {"is_current": True},
            {"_id": 0, "start_date": 1, "end_date": 1, "settled": 1})
        result = compare(latest, metadata)
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        result["settlement_scope"] = settlement_scope_health(current, today)
        print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        # Do not include source exception text; it can contain connection details.
        print("Completion audit failed:", type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

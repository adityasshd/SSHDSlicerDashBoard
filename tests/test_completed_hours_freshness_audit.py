"""Read-only completion audit test: no production connection required."""
import base64
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import zlib


def module():
    location = Path(__file__).resolve().parents[1] / "scripts" / "audit_completed_hours_freshness.py"
    spec = spec_from_file_location("audit_completed_hours_freshness", location)
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_completed_panel_audit_reports_only_safe_metadata():
    audit = module()
    saved = {
        "dashboard_panels": {
            "abc1234567completion": {"available": True, "captured_at": "2026-11-19T09:00:00+00:00",
                                      "data": {"columns": ["User", "Completed Duration", "Completed Tasks"],
                                               "records": [{"User": "Private", "Completed Duration": 3600,
                                                            "Completed Tasks": 2}]}},
            "unrelated": {"data": {"columns": ["User", "Stage", "Duration"], "records": []}},
        }
    }
    doc = {"snapshot_encoding": "zlib-base64-v1", "updated_at": "2026-11-19T09:03:00Z",
           "snapshot_payload": base64.b64encode(zlib.compress(json.dumps(saved).encode())).decode()}
    metadata = audit.snapshot_metadata(doc)
    assert metadata["total_saved_panels"] == 2
    assert len(metadata["completion_panels"]) == 1
    assert metadata["completion_panels"][0]["user_rows"] == 1
    assert "Private" not in json.dumps(metadata)
    stale = audit.compare({"display_date": "2026-11-20",
                           "sort_at": "2026-11-20T06:40:26+00:00"}, metadata)
    assert stale["assessment"] == "completion_panel_older_than_efficiency"
    assert stale["lag_seconds_at_latest"] > 3600


def test_missing_panel_cannot_be_reported_up_to_date():
    audit = module()
    metadata = {"completion_panels": [], "saved_snapshot_updated_at": None}
    assert audit.compare({"display_date": "2026-11-20", "sort_at": "2026-11-20T06:40:26Z"},
                         metadata)["assessment"] == "no_saved_completion_panel"

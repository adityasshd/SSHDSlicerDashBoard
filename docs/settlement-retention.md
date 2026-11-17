# Settlement-based history retention — phase 1

## Policy

- Only periods explicitly marked `settled: true` are eligible to be frozen.
  A previous calendar month is **not** automatically a settled period.
- The active settlement continues to use the existing live/saved reporting pipeline.
- The dashboard renders a settled period exclusively from
  `settlement_snapshots` (immutable, checksum-verified, compressed).
- Historical date inputs and the Today button are disabled while a settled
  period is selected. A missing snapshot displays an unavailable state rather
  than reading live history or claiming zero work.
- Theme and user selection continue to use saved chart-ready panel data.
- Historic Daily Report, User Report, and Workflow History drill-down are **not
  yet covered** by this phase. Do not purge underlying collections.

## Why the existing snapshot is insufficient

`dashboard_snapshot` is a rolling cache with 60 saved chart-panel keys; those
keys incorporate today's date for pending/assigned panels as well as live
mapping/source identities. It cannot serve as a historical settlement archive.

A settled snapshot therefore stores explicit per-period report packets in a
separate, durable record, with `schema_version`, `frozen_at`, SHA-256 digest,
and the exact settlement date bounds. The period ID is `start|end`.

## Source data required for each frozen settlement

1. Final summary panel, including per-user KPIs and funnel.
2. Completion and rework chart matrices.
3. **As-of-close** pending and assigned panels. Today's queues are not valid
   replacements for a past settlement.
4. Trend data for the *exact* settlement date range, including recorded
   history, approvals and efficiency captures.
5. Optional individual user reports. In this phase, any uncovered report is
   explicitly marked as uncovered in `coverage`.

`make_snapshot()` rejects missing panels, arbitrary date ranges, stale queues,
and captures not made on the closure date or the following day in Asia/Kolkata.
For legacy periods, rebuilding a trustworthy final snapshot requires the
original dated evidence or a validated historical export. If that evidence is
missing, leave the period unavailable rather than fabricating final values.

To freeze from pre-validated data, call:

```python
from slicing_dashboard.reporting.settlement_snapshots import (
    make_snapshot, save_snapshot, load_snapshot,
)

payload = make_snapshot(
    period,                  # exact settled period dictionary
    panels_by_kind,          # verified packets: summary, completion, rework, assigned, pending
    trend_capture,           # exact date-range trend
)
save_snapshot(manager.db.mongo_db, payload)
assert load_snapshot(manager.db.mongo_db, period["start_date"], period["end_date"]) == payload
```

This code **only inserts** into `settlement_snapshots`. It does not update,
compact, or delete any existing database documents.

## Observed settlement statuses (inspection 2026-11-16)

- 2026-07-01 through 2026-08-07: settled
- 2026-08-08 through 2026-08-31: settled
- 2026-09-01 through 2026-09-30: *not marked settled*
- 2026-10-01 through 2026-10-31: *not marked settled*
- 2026-11-01 through 2026-11-30: *not marked settled*

Do not change these statuses automatically. Confirm operational closure and
final totals in the settlement-management interface first.

## Before the future archival phase

- Verify dashboard and per-user totals against the existing computed reports.
- Create an external, restorable backup with document counts and checksums.
- Prove the current workflow state is reconstructible after removing old versions:
  latest observation **per event identity** must survive.
- Preserve active event/notification/checkpoint/lease records; preserve user
  mappings and settlement settings.
- Establish the historical behavior of individual/daily/workflow reports.
- Only then implement a separately authorized dry-run/archive/purge command,
  with a bounded set of eligible document IDs and a post-deletion comparison.

**No automated deletion or retention TTL is installed in phase 1.**

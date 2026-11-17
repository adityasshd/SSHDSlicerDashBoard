# Reconciliation audit — 2026-11-17 (IST)

**Status: PARTIAL.** This report distinguishes independently checked source facts
from metrics that the retained data cannot prove. Nothing in this audit authorizes
purging raw data or presenting a reconstructed settlement as final.

## Source collections inspected

- `settlement_periods`: July 1–August 7, August 8–31, September 1–30,
  and October 1–31 were marked settled at inspection time.
- `batches_master`: one current ledger row per batch; not an immutable
  as-of-close state for older periods.
- `batch_returns`: 623 physical documents, 504 unique event IDs.
  119 duplicate event IDs have matching batch IDs and return timestamps.
- `daily_work_reports`: 9 available dates, October 5–13 inclusive.
  This is not complete daily history for any of the four settled periods.
- `settlement_snapshots`: no verified final snapshots at inspection.
- `settlement_snapshot_drafts`: four newly created **non-final** ledger
  reconstructions, separate from the final snapshot collection.

## Independent period checks

| Settlement | Batch rows | Batch video seconds | Unique return events | Returned batches | Available daily reports |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jul 1–Aug 7 | 28 | 2,644 | 2 | 1 | 0 |
| Aug 8–Aug 31 | 137 | 6,913 | 8 | 3 | 0 |
| Sep 1–Sep 30 | 501 | 189,077 | 129 | 71 | 0 |
| Oct 1–Oct 31 | 177 | 510,739 | 137 | 79 | 9 |

Each period was independently reaggregated from `batches_master`, grouped
by user/status, and compared with a separate ungrouped batch count/duration
aggregation. Return event IDs were deduplicated and compared against
`batches_master.return_count`; **all four periods matched**. These figures
represent the **currently retained batch ledger** and are *not* verified
approved-hours, submitted-work hours, or historical queue snapshots.

The return events have 12 documents whose batch IDs do not match the current
`batches_master` collection. Two November batches have more distinct
recorded return event IDs than the ledger's `return_count`; investigate before
claiming current-period event parity.

## Metric contract and chart fixes

1. **Rework intensity heatmap**: a cell's hours are the batch's original
   duration, counted once in the tier of its deduplicated return-event count.
   This is a measure of *batch duration exposed to rework*, **not** hours
   of additional labor spent correcting clips.
2. **Heatmap/KPI scope**: the heatmap default is now `All`, matching the
   returned-batch duration KPI. The Completed / Pending approvals selector
   is wired into both saved and live rendering paths. A scoped chart must
   not be compared to an unscoped KPI without filtering the KPI equivalently.
3. **Rework event count**: never count physical `batch_returns` documents;
   use distinct event IDs for each batch, scoped by the reporting cutoff.
4. **Daily Report**: total output is Fresh + Same-day Rework; Old Rework
   is shown separately and excluded from this particular KPI's total.
   This is a reporting definition, not a statement that old rework consumed
   zero time. Daily task counts include all three buckets.
5. **User Report**: shares the retained daily submission records; missing
   days are unavailable, not zeros. Current batch-status inventory and
   historical submitted-work output are different metrics.
6. **Approved duration**: requires the approved-completion source, not a sum
   of the batch ledger's current duration or the heatmap's rework tiers.

## What prevents final settlement snapshots

A verified final dashboard snapshot requires period-end approved KPIs,
completed and rework charts, **as-of-close** assigned and pending inventories,
and exact-range trends. Daily/User Reports also need submission evidence for
their intended historical drill-down.

The available batch ledger cannot reconstruct the historical pending/assigned
queue at settlement close, and October's nine daily reports do not cover the
full period. Therefore, the four records in `settlement_snapshot_drafts`
are intentionally marked `display_as_final_dashboard: false` and
`safe_for_raw_deletion: false`. The dashboard will continue to show a
missing-final-snapshot state until complete evidence is recovered.

## Remaining work

- Recover period-close captures or audited exports for approved hours and
  assigned/pending inventories.
- Independently compare completion-source approved seconds with chart totals
  at identical date and user scopes.
- Audit task-level return notices and batch membership to measure **actual
  resubmitted/reworked video duration**, separately from batch exposure.
- Inspect the 12 unmatched return documents and November's two event-ledger
  discrepancies; avoid auto-correcting source facts.
- Only then validate and insert immutable final settlement snapshots and
  consider raw-data compaction after backup and parity checks.

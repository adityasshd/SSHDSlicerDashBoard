# Completed Hours versus batch exposure — verification (2026-11-17)

## Reproduced discrepancy, November 1–17, 2026

The date-filtered annotator-efficiency completion source reports
227,009.866 seconds = **63:03:30** (displayed rounded) across **1,710**
completed tasks. It is the source used by the main Dashboard Completed Hours
KPI and the per-user Completed Duration panel.

The current batches_master ledger contains **220 batches** with batch_date
in November 1–17 and status batch_completed. Their whole original duration
is **546,163 seconds = 151:42:43**.

Of those, November 4 has **184 currently completed-status batches** with
**487,209 seconds = 135:20:09** original video. However the independently
dated completion source recorded only **18:36:29** for November 4.
**108** of those November 4 batches also had October Admin-approved events
totalling **81:32:01** of original batch duration.

The gap comes from mistaking cohort date, latest batch state and original
video length for completed tasks during the requested range.

## Why tier-specific 63-hour completion cannot be proven

- None of the 334 November 1–17 batch ledger rows has a legacy batch number.
- Neither slicing_master nor slicing_history has a November completed_date
  task record in the retained collections inspected.
- workflow_events task observations stop in early October.
- Per-day annotator-efficiency captures contain user-level completed seconds,
  not batch IDs or return-tier linkage.

Therefore, allocating the 63 completed hours into No Rework, 1 Rework,
2 Reworks and 3+ Reworks would require inventing task-to-batch evidence.

## Corrected chart behavior

1. The default Verified Completed Hours heatmap takes exactly the same
   date-range completion panel as the Completed Hours KPI and displays one
   accurate per-user completion column. No inferred rework-tier values.
2. The All/Completed/Pending batch modes still show the original video
   duration by recorded return tier, explicitly labelled batch exposure.
3. The Approval Hours view uses the exact completion panel for
   Admin-completed source status. Leader/Auditor *approval-date* hours
   remain unavailable. Completed source status is not an Admin event date.
4. The Approval Batches view retains nested distinct latest-status batch
   counts, with original cohort video-hour hover fields removed.
5. An unavailable or mismatched capture cannot be replaced with a whole
   batch duration. Saved-through dates are disclosed.

## Required for complete approved-duration-by-return-tier accounting

Capture stable task ID, batch ID, completed task video seconds, verified
Admin decision timestamp, unique return event ID, reviewer and event date.
Reconcile task-to-batch links and as-of-period status first; then assert
the sum of four tier-attributed completed durations matches the exact
Completed Hours total for identical dates and user mapping.

No MongoDB data was changed, removed, or backfilled in this work.

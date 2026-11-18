# November 2026 return history — verified snapshot audit

Audited on 2026-11-17 from retained MongoDB `slicing_dashboard.batch_returns`
and `slicing_dashboard.batches_master`. **No source records were changed.**

## Date-correct observed rework events (November 1–17)

The upstream `returned_at` field contains timestamps without a timezone.
The existing daily source treats naive upstream timestamps as Asia/Shanghai,
then converts them to Asia/Kolkata for reporting. The audit below uses that
same conversion, so event counts reflect *India-local return dates*.

| Date (India) | Observed distinct returns |
| --- | ---: |
| Nov 2 | 1 |
| Nov 3 | 2 |
| Nov 4 | 83 |
| Nov 5 | 2 |
| Nov 6 | 1 |
| Nov 8 | 1 |
| Nov 11 | 4 |
| Nov 12 | 1 |
| Nov 13 | 6 |
| Nov 14 | 7 |
| Nov 15 | 2 |
| Nov 16 | 2 |
| Nov 17 | 8 |
| **Total** | **120** |

These 120 observed return occurrences affect **98 distinct batch IDs**.

Latest saved status for those return occurrences:
- **91** currently marked `batch_completed`.
- **22** linked to batches currently in a review status (`batch_reviewing`,
  `batch_pending_leader_review`, `batch_pending_auditor_review`,
  or `batch_pending_admin_review`).
- **5** linked to batches that are assigned/unassigned or in another status.
- **2** associated with a batch ID absent from the latest saved batch ledger.

These are **event counts** by an affected batch's **latest** state, not
historical state transitions on each event's date. Nor are they video hours,
additional labor hours, or source-date approved-task hours.

## History reconciliation and coverage

The endpoint is `GET /api/requests/batch-return-history?workflow_type=slice`.
The published contract permits `limit` up to 100 and optionally
`operator_id`, but has no documented pagination. Historical events are
retained append-only in the saved return cache. As such, a return count is a
**minimum observed count**, never a guaranteed exhaustive lifetime count.

The Collector's synthetic IDs include the account from which the event was
observed. A duplicate sighting under a second operator ID must not inflate
return cycles. The reconciliation treats these synthetically identified
returns as the same event when they share batch ID and normalized returned-at
instant; distinct genuine upstream event IDs remain distinct even if their
timestamps happen to match.

Any batch without a matching ledger entry stays in the audit as unlinked.
Other statuses are not silently treated as Pending Review. Selected-member
filters use the *current assigned member*, not the unknown reviewer.

## Dashboard behavior

- **Workflow History** gains a current-month trend and paginated per-batch
  observed return table.
- **Rework intensity heatmap** exposes only Completed and Pending Review,
  both referring to the batch's latest saved status.
- Heatmap cells and the associated breakdown KPI display **original batch
  video duration** by observed return tier. This is different from the
  official verified **63:03:30** source-date Completed Hours for Nov 1–17;
  those two figures are intentionally not forced to match.
- The separate main Completed Hours KPI and approval-hours source are
  unchanged, because task-to-batch approved-duration attribution still
  cannot be verified.

Everything is implemented and tested on a feature branch; there is no
production merge or MongoDB mutation in this change.


## November 18 evidence-only return-tier classification (development branch)

The Dashboard's **rework tier heatmap** has a fifth column, **Unknown**.
Known tiers No / 1 / 2 / 3+ are assigned only when the retained unique
return-event occurrences agree with the latest batch ledger's
`return_count` and every identifiable return timestamp parses.
Unmatched or missing ledger counts, extra/missing return events, and
unparseable return records tied to a batch move that batch to Unknown.
For a selected historical cutoff, compare the full saved occurrence count
to the current ledger for completeness, then use only dated observations
through that cutoff to choose the verified tier.

Unknown contains the **number of affected batches**. The original video
duration remains available in the underlying audit frame, but is deliberately
**not displayed as rework duration** in the heatmap or Overview. Both
now use batch counts and all five tier counts reconcile to inventory. Legacy saved rework captures cannot certify
Unknown classification; they need a new capture. Because the upstream
history API lacks full pagination, a numerical ledger match increases
confidence but does not independently establish lifetime completeness.

This change is **feature-branch-only**, not an upstream data correction,
production deployment, or historical settlement backfill.


## November 18 — last-update date fallback

The Assigned Work chart reads current task queue items from /api/slice/tasks.
When a task lacks an assignment date or reliable return date, a valid
task-side updated_on (or updated_at/status_updated_at/modified_at) is used
only to compute the bar's age color. Its hover states **Last task update**
rather than inventing assignment or return time. The actual event date, when
available, takes priority. A future or unparseable timestamp stays unknown.

A cached batch-master `last_updated` is a **Collector sync timestamp**, not
an upstream task event; it must never be used for this fallback. Grouped live
task segments use their most recent task-side update. Viewer snapshots
require a fresh assigned panel capture for the new fields.

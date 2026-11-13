# Friday pending-review audit — 2 November 2026

## Finding

The large drop in pending-review hours cannot be classified as bulk approval.
The upstream service no longer resolves 52 of 53 batches marked pending in the
retained Friday batch observations. All 52 return HTTP 404 with
`REVIEW_BATCH_NOT_FOUND` from the batch failure-summary endpoint. The remaining
batch still exists and is reported as pending Admin review.

These responses establish that the records are unavailable through the current
source API. They do not establish whether an administrator deleted, archived,
migrated, or otherwise removed the records from the accessible scope. An upstream
administrative audit is needed to determine the operation and actor.

## Friday dashboard capture

The retained pending panel was captured on **30 October 2026 at 14:48:12 India
time** (`2026-10-30T09:18:12.633241+00:00`). It contains:

| Review stage | Tasks | Video duration |
| --- | ---: | ---: |
| Leader | 284 | 08:02:01 |
| Auditor | 1,817 | 56:43:46 |
| Admin | 0 | 00:00:00 |
| Total | 2,101 | 64:45:47 |

| Person | Friday pending tasks | Live pending task records in first audit capture |
| --- | ---: | ---: |
| Akash | 555 | 0 |
| Priya | 281 | 23 |
| Komal | 286 | 10 |
| Aditya | 265 | 76 |
| Riya | 250 | 0 |
| Rajni | 393 | 79 |
| Ranjeeta | 71 | 57 |
| Total | 2,101 | 245 |

The live capture contains 16 Leader-review records (2,252 video seconds), 229
Auditor-review records, no Admin-review task records, and no rework task records.
The 229 Auditor records all report `duration_seconds=0`, `version=1`, and
`slice_batch=0`. They belong to SSHD-S-Aditya6 (70), SSHD-Priya1 (23), SSHD-Rajni
(79), and SSHD-ranjo2 (57). Their updates predate Friday. An hours chart plots
these records at zero height even though their task counts remain nonzero.
The queue endpoint does not provide reliable video hours for them. A subsequent
cross-check recovered their actual time ranges from a different endpoint; see
the follow-up below. Zero queue duration does not prove timing data was erased.

These two task totals describe captures at different times, not an exact cohort
reconciliation. The saved Friday panel retains account/stage aggregates, not its
individual task IDs. Work continued during the audit: the later full inventory
already contained 17 Leader-review tasks. Do not label the numerical decrease
as approved work.

## Retained Friday batch records

For each batch, select the latest retained Friday observation no later than the
pending panel capture. Of the 53 distinct batches marked reviewing or pending
Auditor/Admin review, 52 now return `REVIEW_BATCH_NOT_FOUND`:

| Person | Missing pending batches | Still accessible batches |
| --- | ---: | ---: |
| Akash | 14 | 0 |
| Priya | 9 | 0 |
| Komal | 9 | 0 |
| Aditya | 5 | 0 |
| Riya | 7 | 0 |
| Rajni | 7 | 1 |
| Ranjeeta | 1 | 0 |
| Total | 52 | 1 |

The missing batches retained 1,921 pending task counts in their historical batch
records. That is a separate source from the 2,101-task queue capture; batch and
task states can disagree, so these quantities must not be equated or added.

Examples:

- Aditya / SSHD-Adi: `ab_2125c86f86ff4b6885387a1aeeda883e` was pending Auditor
  review in retained Friday data. The current batch-detail read returns 404
  `REVIEW_BATCH_NOT_FOUND`; an exact dashboard batch filter also returns no row.
- Rajni / SSHD-Slicer5: `ab_842e5d0d37634fa191c636024900e43e` still returns 200
  and appears in the batch dashboard as `batch_pending_admin_review`. It has 58
  task memberships, zero reported duration, and zero task-level pending-review
  count. The stage label alone does not prove 58 current pending videos.

The full current task inventory was read through 18 cursor pages, with a stable
reported total of 3,424 and no repeated cursor. Friday's summary reported 12,895
tasks. That broader drop is consistent with substantial source-side inventory
removal, but the two endpoints/capture dates do not provide a deletion ledger.

## Approval evidence and limits

Retained observed workflow events contain five dated Leader batch approvals
between Friday and Monday, three of which precede the Friday pending-panel
capture. The live reviewed-batches endpoint returns two approvals in the queried
Friday–Monday range: SSHD-Slicer7 and SSHD-Ranjeeta, both on Saturday at about
18:19 India time. Both rows currently report completed batch state. Review
visibility belongs to the configured Leader account; this is not a complete
administrator audit of all reviewers. No bulk approval of the missing 52 batches
was established. Synthetic milestones were excluded from this investigation.

## Evidence

Local evidence is under `data/reports/friday-pending-audit-2026-11-02/`:

- `friday-pending-panel.json`: original Friday queue aggregate.
- `friday-pending-batches.json`: retained pending batch observations.
- `all-friday-batch-checks.json` and `friday-batch-outcomes.csv`: all 53 direct
  batch checks with account, previous status, HTTP result, and check timestamp.
- `slice_submitted.json`, `slice_pending_auditor_review.json`, and
  `slice_pending_admin_review.json`: current queue captures.
- `all-current-tasks.json`: complete cursor-paginated current inventory.
- `reviewed_batches-first.json`, `reviewed_tasks-first.json`, and
  `weekend-observed-events.json`: available dated review evidence.

This audit only read upstream and retained data and wrote local audit artifacts.
It did not change assignments, reviews, permissions, or shared database records.

## Follow-up: alternate APIs and likely explanation

The strongest current hypothesis is upstream archival or task reconstruction
that removed or hid original assignment batches and retained many tasks as
unbatched records. This is an inference, not an established operation or actor.
It coexists with a confirmed inconsistency in the API's duration fields.

### Recoverable pending hours

`POST /api/tasks/assigned/overview` works with the **authenticated Leader's own
user ID, 803**. No member identity was substituted. Its complete, cursor-paginated
response contained 282 review-task rows at this later capture: 26 submitted and
256 pending Auditor review. These are later live totals, not Friday's cohort.

Every one of the 229 zero-duration Auditor task IDs from the first audit was
present in that alternate response with a positive `end - start` range:

| Account | Matching tasks | Recovered duration |
| --- | ---: | ---: |
| SSHD-S-Aditya6 | 70 | 01:00:17 |
| SSHD-Priya1 | 23 | 00:55:19 |
| SSHD-Rajni | 79 | 01:58:32 |
| SSHD-ranjo2 | 57 | 00:59:47 |
| Total | 229 | 04:53:55 |

All 229 still have no assignment-batch ID in this response. Direct task-detail
samples from all four accounts independently confirm positive ranges. Thus the
dashboard's use of `duration_seconds` from `/api/slice/tasks` hides real pending
hours. It does not establish that those 229 videos disappeared or were approved.

### Evidence of changed task representation

Compare the 1,636 retained pending task records in the older master capture
(approximately 1 October) with the 3,424-row current queue inventory. Only 80 IDs
overlap. For 74 of those IDs:

- The old nonzero slice batch is now zero.
- The older version counter is higher than the current counter, which is one.
- The queue's duration field changed from a positive value to zero.
- Ten formerly submitted and 64 formerly Auditor-pending rows now report
  completed status. Their completion dates and approval paths are not established
  by this older/current comparison.

Duration changes in that comparison are **queue-field changes**, not proof of
lost timing. For example,
`manual_cut_18579759021_20260922_080011_00017_task_0` previously had batch 1,
version 3, and 26 seconds. The current queue reports batch 0, version 1, and
zero seconds, while both `/api/tasks/{id}` and `/api/videos/{id}/tasks` still
return its 0–26 second time range and 23 approved actions.

The user's separate Unbatched example,
`manual_cut_19868278079_20260822_064745_00012_task_0`, exists in both direct task
and video-task reads. It reports completed status, batch 0, version 1, and 21
approved actions. Its task range and all 21 action ranges are zero in the tested
responses. The work records survive, but these APIs do not expose usable timing
for that particular example.

The version/batch changes support reconstruction or a changed source projection
more strongly than an ordinary review transition. They do not establish that
the transformation happened during the weekend: old timestamps may be preserved,
and the retained task-level baseline predates Friday.

### Other endpoint checks

| Endpoint | Result |
| --- | --- |
| `/api/slice/tasks` | Full queue capture; numerous zero durations and zero batch numbers. |
| `/api/tasks/assigned/overview` | 200 using the authenticated Leader ID; all 229 matching Auditor task durations recoverable. |
| `/api/tasks/{id}` | 200 on tested tasks; confirms surviving task records and, for sampled Auditor tasks, positive time ranges. |
| `/api/videos/{id}/tasks` | 200; independent task-list representation, including saved action counts. |
| `/api/tasks/{id}/actions` | 200; the user's example still has 21 approved action records. |
| `/api/review/batches/{id}/failure-summary` | 52 of 53 retained Friday pending batches return `REVIEW_BATCH_NOT_FOUND`; one survives. |
| `/api/review/reviewed-batches` and `/api/review/reviewed-tasks` | Available review evidence does not establish bulk approval of the missing backlog; account visibility is limited. |
| `/api/requests` | 200; four current sampling-pass notices, not a complete deletion or migration audit. |
| `/api/admin/archive-recalls` | 403; administrator permission required. This endpoint is a possible archive-related lead, not an established deletion ledger. |
| `/api/admin/data-flow/{task_ref}` | 403; administrator data-flow access denied. |
| `/api/tasks/overview` | 403, `TASK_POOL_ADMIN_REQUIRED`. |
| Separate service `slicer.4dity4.tech`: schema and Friday daily-work reads | Both HTTP 402; unavailable as an independent historical cross-check. No source credentials or cookies were sent to this service. |

To identify the precise operation, time, and actor, an upstream administrator
must inspect the restricted data-flow/audit evidence or server/database history.
The current evidence establishes missing batch accessibility, surviving work
records, changed task representation, and recoverable hours hidden by the queue
API; it does not prove permanent deletion of all original work.

Additional local evidence: `same-task-before-after.json`,
`other-api-checks.json`, `auditor-detail-cross-checks.json`,
`allowed-assigned-overview-full.json`, and `recovered-auditor-duration.json`.

The subsequent [additional API investigation](pending-review-api-discovery-2026-11-02.md)
verified a complete 256-ID Auditor queue against the alternate overview, totaling
06:54:31, and a 30-task actionable Leader queue with batch links and time ranges.
It also documents the role/date/preview limits of the other tested APIs.

# Additional pending-review API discovery — 2 November 2026

## Usable responses

The live OpenAPI specification has 336 paths, compared with 314 in the retained
29 October specification. This pass made 22 completed read-only HTTP probes across 13
documented endpoint paths, including bounded filter/date variants. No task,
review, assignment, permission, or shared database record was changed.

The configured source account is Leader 803. All calls use its existing session;
no other user identity or reviewer role was substituted.

| Purpose | Endpoint | Verified response and limits |
| --- | --- | --- |
| Complete current Auditor IDs | `GET /api/slice/tasks/queue?status=slice_pending_auditor_review` | 256 IDs; `total_capped=false`, below `max_queue_size=10000`. Does not provide durations or historical batch membership. |
| Task time ranges and available assignment links | `POST /api/tasks/assigned/overview` with authenticated user ID 803, cursor pagination, `status_group=all` | The previously saved complete response contains all 256 Auditor IDs from the newly fetched ID queue, with no unmatched IDs in either direction. Their ranges total 24,871 seconds (06:54:31). The response also covers Leader-pending tasks; it is a current role-dependent view, not a submission-event ledger. |
| Current actionable Leader review tasks | `GET /api/review/tasks?workflow_type=slice` | 30 rows, `has_more=false`. All 30 have assignment-batch IDs and positive start/end ranges. Includes batch status/number, task counts, review scope IDs, and action previews. |
| Review history and reviewer activity | `GET /api/dashboard/reviewer-personal` | Dated summary, daily series, and recent task-review rows for the authenticated reviewer. Friday–Monday summary has 29 approved ledger rows, 27 on Monday and two on Saturday. The weekend-only response confirms two decisions. It is not a complete all-reviewer history. |
| Reviewer summary | `GET /api/dashboard/reviewers` | Confirms current account's 29 approved ledger rows in the queried Friday–Monday range. Only one reviewer is visible. Pending quantities are role/date scoped and cannot replace an unrestricted all-age queue. |

The first two sources independently agree on all **256 Auditor task IDs**. Of
these, 229 were identified in the earlier zero-duration queue capture; their
recovered duration is 04:53:55. The remaining 27 records contribute 02:00:36.
These are live capture differences, not evidence of Friday cohort resolution.

Recommended current-queue data path: enumerate authoritative stage-specific
task IDs, match by exact ID to fully paginated task time ranges, and compute
duration from validated `end - start`. Require every queue ID to be accounted
for. A role-limited empty review queue must not become a zero for other stages.
Never substitute a preview or unrelated aggregate for missing task rows.

## Role restrictions and misleading alternatives

| Endpoint | Result | Implication |
| --- | --- | --- |
| `GET /api/review/tasks` with Auditor status | 200, zero rows | The Leader's actionable review view cannot enumerate Auditor work. The separate Auditor ID queue still contains 256 tasks. |
| `GET /api/tasks/assigned` | 400, `USE_PAGINATED_OVERVIEW` | The server explicitly directs review-role callers to the paginated POST overview. |
| `GET /api/review/sampling-pool` | 200, no eligible Leader-stage candidates | Sampling eligibility is not the complete pending workload. |
| `GET /api/review/sampling-summary` | 200, no eligible Leader-stage groups | Does not recover missing Friday batch membership. An exact missing-batch query also returns none. |
| `GET /api/review/efficiency-monitor` | 403, Admin permission required | Unavailable to this login. |
| `GET /api/requests/batch-return-history` | 403, Member permission required | Unavailable using the actual Leader identity. |
| `GET /api/dashboard/task-duration-summary` | 200, 105,659 tasks and 432.4631 video hours for the requested pending-status filter | No verified matching group scope; cannot be used as this group's queue total. |
| `GET /api/dashboard/statistics` | 200, broad task/action/work/video counters | No exact task membership reconciliation; does not recover original batches or certify Friday's backlog outcome. |
| `GET /api/dashboard/user-statistics` | 200, total/online user counts | Irrelevant to the missing review cohort. |

## Drilldown and historical limitations

`POST /api/dashboard/drilldown` accepts `task_list`, `assignment_batches`, and
`review_work_logs` targets, but its output is a **preview** without a complete
cursor-paginated history contract.

- An Auditor-status task-list query without explicit dates returns only 27 rows;
  its response range defaults to the current source day. It omits the 229 older
  Auditor IDs. This does not mean those older tasks are absent.
- An October-to-November task preview returns IDs/statuses but no durations,
  original batch IDs, or actual submission timestamps.
- A query for the known missing Aditya batch returns an empty assignment-batch
  preview. The same batch is also absent from the review queue and sampling
  summary. The earlier direct batch-summary call returns `REVIEW_BATCH_NOT_FOUND`.
- The review-work-log drilldown returns an empty preview even when the reviewer
  dashboard reports 29 approved ledger rows. Therefore that empty preview is not
  evidence of no approvals.
- The dated reviewer APIs expose task-level review-work-ledger quantities. These
  are distinct from the retained batch-review log events and synthetic milestones.
  In particular, the current Friday-only work-ledger summary reports zero, while
  the earlier retained source batch-review evidence contains three Friday Leader
  actions. Neither API alone is a complete historical reconciliation.

An attempted explicit broad-date Auditor preview did not execute because a new
login was unavailable. It is not counted among the 22 completed probes. The already
verified queue/overview ID match supplies the complete current Auditor inventory
without relying on that preview.

No newly tested permitted endpoint reconstructs the missing 52 original Friday
assignment batches or identifies the administrative operation that made them
unavailable. The previously tested admin archive and data-flow APIs require
administrator access. The separate analytics service remains HTTP 402 in the
earlier same-day check.

## Local evidence

Raw source responses and request summaries are under
`data/reports/pending-api-discovery-2026-11-02/`:

- `openapi.json`: live operation inventory.
- `probe-summary.json`: 16 initial probes across 13 paths.
- `followup-summary.json`: six bounded follow-up probes.
- `queue-snapshot.json`: complete 256-ID Auditor queue.
- `cross-endpoint-reconciliation.json`: exact ID equality and duration total.
- `review-queue.json`: the 30 Leader review-task rows and batch metadata.
- `reviewer-personal.json`, `friday-reviewer-personal.json`, and
  `weekend-reviewer-personal.json`: date-scoped review evidence.

The matched time ranges are in the earlier complete capture:
`data/reports/friday-pending-audit-2026-11-02/allowed-assigned-overview-full.json`.
Its Auditor ID set equals the later queue snapshot exactly; the Leader workload
changed between captures. All timestamps and raw API payloads are retained for
review.

The subsequent [local recovery](pending-review-recovery-2026-11-02.md) adds a
verified task-range fallback, exports the recovered records, and confirms that
the pending-review chart renders the available hours.

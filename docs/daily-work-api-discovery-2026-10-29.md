# Daily-work API investigation — 29 October 2026

## Finding

The live FastAPI schema was fetched again from
http://120.79.192.226/openapi.json: **314 paths, 355 operations**. Read-only
requests authenticated with the existing configured account, whose role remains
5 (Leader). No credentials, permissions, upstream tasks, deployments, shared
reports, or collector schedules were changed.

There is a working source for **dated account status summaries**, but none of
the tested permitted endpoints exposes the task submission timestamps needed to
rebuild the existing **Fresh + Same-day Rework**, with **Old Rework** separate,
daily measure. Replacing that measure with efficiency values would change its
meaning. This is an API permission/data-contract limitation, not a login failure.

## Relevant live endpoints

| Endpoint | Observed result | Use and limitation |
| --- | --- | --- |
| `POST /api/dashboard/annotator-efficiency` | 200; 93 accounts with `role=2, leader_id=803, page_size=200` | Best immediate fallback for per-person current completion, pending review, and rework status by source date. Preserves video seconds, counts and measured work seconds as separate metrics. No task-level submission time or fresh/same-day/old classification. |
| `POST /api/dashboard/annotator-efficiency-overall` | 200; 93 users | Reconciles the account summary. Its video-duration/count totals matched the complete account response in this capture. |
| `GET /api/user-groups` | 200; authorized organization ID **13**, root Leader **803** | Resolve the organization before using v2 APIs. |
| `POST /api/v2/dashboard/annotator-efficiency` | 200; 93 accounts with `group_id=13` | Returns enhanced-efficiency fields under `user_list`, rather than the older endpoint's `items`/status-duration schema. Not a drop-in replacement. |
| `POST /api/v2/dashboard/user-efficiency-enhanced` | 200; 93 accounts with `group_id=13` | Same response data as v2 annotator efficiency in this capture. Video durations and first-pass values are insufficient for the daily-work calculation. |
| `POST /api/dashboard/user-efficiency-enhanced` | 200 | Activity, submitted-task counts, work seconds and ratios. Checked examples have submissions with zero video seconds. |
| `POST /api/dashboard/user-activity` | Unscoped request timed out; one-member request returned 200 | Useful account activity diagnostics. Not submitted video-output evidence. |
| `GET /api/dashboard/slice` | 200 | Current funnel, account breakdowns and latest-submit indicators. The dated range explicitly uses UTC+08:00. Its submitted-duration definition covers current pending statuses, not all submission events. |
| `GET /api/dashboard/batches` | 200; no batches for this date | Scope and batch summaries; no complete task submission history. Empty batches must not turn existing account activity into zero work. |
| `GET /api/slice/tasks` | 200; cursor pagination metadata | Allowed group inventory with task ID, account, batch and duration. **No `slice_submitted_at`** in checked rows. `updated_at` is not a submission timestamp. |
| `GET /api/slice/tasks/queue` | 200 | Task IDs and queue metadata; not submission history. |
| `POST /api/dashboard/drilldown` | 200 for `metric_key=task_list` and `assignment_batches` | Limited preview without submission timestamps. `submitted_count` and `review_pending_count` keys returned 400; use target keys from dashboard drilldown definitions. |
| `GET /api/review/reviewed-tasks` | 200 | Actual dated review decisions, useful for approval/return audit. Review timestamps do not establish submission dates. |
| `GET /api/tasks/{task_id}` | 200 on a reviewed task; 409 on a locked task | Checked successful response also omits submission timestamps. Not a source for daily submission inventory. |
| `GET /api/videos/{video_id}/tasks` | 200 | Checked task records have geometry and current state, without submission timestamps. |
| `POST /api/tasks/assigned/overview` | 403, `ACTOR_IDENTITY_MISMATCH` for a group member | Restricted to the authenticated account's own tasks; not a Leader-wide fallback. |
| `POST /api/tasks/overview` | 403, `TASK_POOL_ADMIN_REQUIRED` | Existing daily collector's required inventory is still administrator-only. |
| `GET /api/admin/data-flow/{task_ref}` | 403, `FORBIDDEN` | Task-history access is also unavailable to this login. |
| `POST /api/dashboard/task-duration-summary` | 200 | Aggregate duration cross-check only; no per-account task evidence or fresh/rework split. Do not assume it has the same group/date basis as daily submissions. |

The `statistics` request timed out, so its response semantics were not verified.

## Important incompatibilities

**Leader ID is not organization ID.** The older dashboard scope and task rows
use `group_id=803`, while `/api/user-groups` identifies organization `id=13` with
`root_leader_id=803`. Both v2 requests returned an empty `user_list` when passed
803, then returned 93 accounts when passed 13. Resolve the correct ID for each
API family; never globally replace 803 with 13.

**The enhanced metrics cannot replace video-output metrics.** In today's
captured account responses, user 3969 had 37 submissions and 3,054 submitted video
seconds in the older efficiency API. Enhanced efficiency reported 37 submitted
tasks, 10,759 work seconds, and **zero video seconds**. The full v2 response had
379 submitted tasks and just 910 video seconds. These fields require a different
interpretation or an upstream correction before use as daily video output.

**The old total fields are not daily totals.** October 6 and October 29 both
returned all-account `total_count=12,895` and
`total_duration_seconds=1,141,423`, while dated status metrics differed.

**Status and event measures cannot be interchanged.** Today's older efficiency
capture contained 370 submitted/pending tasks (37,389 seconds), 350 completed
tasks (33,975 seconds), and 202 tasks in rework (17,898 seconds), before local
person exclusions. These are raw account status results, not a certified daily
work total. The collector's existing `EfficiencyHistory` deliberately stores
them as source-date current status. The API's UTC+08 day also differs from the
daily report's India day by 2 hours 30 minutes. Aggregates cannot be shifted
accurately without timestamps. Responses were captured at different moments
during active work, so small changes between captures are expected.

## Concrete solution

1. **Available now: a clearly labeled status fallback.** Reuse the existing
   `reporting/efficiency_history.py` capture and validation pipeline for a
   separate "Source-date current status (UTC+08)" section on Daily/User Report.
   Show completed video, submitted/pending video, current rework and activity
   separately. Keep the existing daily-work availability and saved evidence;
   do not write efficiency summaries into `daily_work_reports`, invent a fresh
   split, sum cumulative totals over dates, or relabel work seconds as video.
   `scripts/backfill_efficiency.py` already supports recovering this status
   history. No shared backfill was executed by this investigation.

2. **Restore the current daily definition:** use an authorized administrator
   inventory login on the external collector, or request a narrow upstream
   Leader-readable inventory contract. The smallest useful extension is adding
   `slice_submitted_at` to the existing permitted `/api/slice/tasks` response,
   ensuring it includes every relevant current task state and supports complete
   cursor pagination. Needed fields are ID, slicer ID/name, batch, duration and
   the actual submission timestamp. Apply India-day filtering locally, then
   retain the existing return/review classification. Prefer a date-bounded feed
   so collection does not scan the group's whole inventory. A latest-state feed
   still cannot recover every earlier submission attempt.

3. **For reliable future history without polling privileges:** persist confirmed
   submission events into an append-only event ledger, ideally emitted by the
   upstream server. An operator userscript is a secondary capture option only
   after delivery retries, durable deduplication and coverage checks. The local
   Submitter/Analytics projects already contain a reporter and
   `/api/submissions/record` / `/api/submissions/daily-work`, but their configured
   public service returned **HTTP 402** for both schema and daily-work reads in
   this check. Its existing database code also fabricates a prior fresh event
   when first seeing rework; that behavior must be removed before treating the
   service as historical evidence. Unknown first-work dates must remain unknown.

The first option is a useful, implementable partial recovery with current
permissions. The second restores the existing report semantics. The third
prevents future history gaps but cannot manufacture missed historical events.

## Evidence and repeatable checks

Local ignored artifacts are under `data/reports/api-discovery-2026-10-29/`:
`openapi.json`, readable full `endpoints.md`, structured `endpoints.json`, and
named API response captures. Cookies and credentials are not included.

Run from the dashboard project to fetch a fresh schema and the primary read-only
probes, then check the permitted drilldowns and correctly scoped v2 APIs:

```powershell
.venv/Scripts/python.exe scripts/discover_daily_work_api.py --date 2026-10-29
.venv/Scripts/python.exe scripts/discover_daily_work_api.py --date 2026-10-29 --details
```

The command requires collector mode because the project's viewer runtime rejects
upstream reads. It saves local evidence only; it does not backfill shared reports.

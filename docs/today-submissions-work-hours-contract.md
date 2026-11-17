# Daily submitted video output and real work-time accounting

## Immediate dashboard replacement

The old Approval Progression pyramid is replaced by the **Today's submitted
video** lollipop. It deliberately ignores dashboard date-range filters:
"today" is computed in Asia/Kolkata from the current date. It uses only the
same verified date-stamped submitted-task evidence as the Daily Report.

Four lollipops show a non-additive total plus three disjoint parts:

1. **Submitted today — all**: submitted video seconds for task IDs observed
   on the target day, across all three buckets.
2. **New videos**: submissions with no recorded return before submission.
3. **Old rework**: submitted video from rework returned on a prior date.
4. **Same-day rework**: submitted video returned earlier in the same India
   calendar date and resubmitted that date.

**Submitted today = New videos + Old rework + Same-day rework.** Each
individual task ID appears only once in the final dated report.

The pre-existing Daily Report has a legacy `Total Duration` field defined as
**New + Same-day rework**; it excludes Old rework. This lollipop therefore
**does not reuse that legacy total**. Its source is the same saved per-user
task-submission rows, with an explicitly different all-submissions sum.
The legacy Daily Report and other KPI definitions remain unchanged pending
an agreed migration.

A return event, a batch's current completed state, an Admin approval, or the
batch's *original total duration* is not evidence that a task was
**resubmitted today**. Never substitute them.

## Source coverage as of November 17, 2026

The retained `daily_work_reports` MongoDB collection ends on October 13.
The November return events are available, but no dated task submission
records were retained for November 17 as of the audit. Accordingly, the
new chart correctly shows **Unavailable**, not 0 or an invented estimate.
The existing Collector source scan fails with authenticated HTTP 403 for
`POST /api/tasks/overview`. Restoring sanctioned endpoint access or an
equivalent authorized task-submission event feed is prerequisite to a live
today chart.

For saved today-only snapshots, show capture timestamp; the day's output is
provisional until explicit end-of-day reconciliation is recorded.

## Separate concept: actual active working hours

**Video duration is not elapsed person-time.** An operator may edit a
10-minute clip for 35 minutes or process a 40-minute clip in 15 minutes.
Even the elapsed time between earliest and latest submission includes
breaks and review queues.

Introduce explicit, append-only task activity/session events:

`event_id, actor_id, task_id, batch_id, session_id, kind,
server_timestamp_utc, source, revision, workflow_type`

where `kind` is one of `work_started`, `work_paused`,
`work_resumed`, `work_stopped`, `submission_saved` or
`submission_finalized`.

For reliable labor hours:
- Match start/resume to pause/stop intervals per actor/session.
- Record inactivity separately rather than assuming users were active.
- Split intervals at Asia/Kolkata midnight boundaries.
- Union overlapping intervals per actor; do not double-count multitasking
  or multiple tasks in the same active session.
- Mark unpaired intervals, absent pauses, timestamp anomalies, and missing
  IDs **unverified** rather than inferring elapsed work.
- Classify the session as New, Old Rework or Same-day Rework using *review
  return time before work/submission*, not latest batch status.
- Keep both submitted **video hours** and verified **active labor hours**
  in distinct columns with separate provenance and coverage flags.
- Include incomplete work sessions that have not resulted in submission in
  labor tracking, but not in submitted video output.

Until reliable time events exist, **actual labor hours = Unavailable**.
No video-duration weighting factor is justified from current evidence.
Once collected, independent daily assertions should hold:

`submitted_video_seconds = new + old_rework + same_day_rework`

`verified_active_labor_seconds = union_of_accepted_work_intervals`

The first is throughput; the second is actual active time, with neither
equated to Admin-approved hours or batch-return duration.

## Safety

No changes to source permissions, MongoDB data, Collector schedules, or
production `main`. Render the lollipop from saved report snapshots only.

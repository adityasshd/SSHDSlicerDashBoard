# Submitted work evidence policy — November 17–18, 2026

## Revised dashboard display (November 18)

The main Dashboard now prefers the **dated Daily submission report's VIDEO
durations**. It renders a **per-user line** for all submitted video hours and
two separate **vertical lollipops** for **Old rework** and **Same-day rework**.
These reworks are already included in submitted duration, so their markers
must not be added to the line. Durations come from the report's three
disjoint buckets; `Total Duration` in the legacy Daily Report excludes old
rework and must not be substituted.

When the dated Daily submission report cannot be verified (for example,
access to historical task-submission timestamps is denied), the chart may
still render a **line-only submitted-status inventory snapshot** from the
saved annotator-efficiency capture for the current India-local date.
This fallback is explicitly labeled **"NOT verified as submitted today"**:
it measures video duration in the source's submitted task status, *not*
work submitted during that calendar day. It contains **no old/same-day
rework lollipops**, since neither task status nor a return notice proves
the requisite submission/return chronology. In both modes, an unavailable
video duration stays unavailable and is never presented as zero.

Both render paths use selected-user mappings, don't make upstream API calls
while painting, and exclude screen, session, or worklog duration.

The count-only chart previously used is retained only as a historical
interim implementation. Its validation function is still available for
other explicit task-count analysis, but no longer drives the dashboard.

## Decision: count video duration, not screen or worklog time

The dashboard pays/credits operators based on the **duration of videos
submitted**, not the time they spend logged in, editing or on a webpage.
No screen-time, heartbeat, worklog, session-time or elapsed-time metrics
belong in the submitted video-hours chart.

For each task with a verified final submission timestamp in the selected
India-local day, count its submitted video duration **once** using a stable
task ID and that day's authoritative submission evidence. Categorize it:

- **New video:** no earlier return/rework event for the task or its batch
  before the submission timestamp.
- **Old rework:** an earlier return/rework occurred on a prior India-local date
  and the video was submitted during the selected day.
- **Same-day rework:** the task or batch was returned earlier on the
  submission date, and the revised video was submitted that same day.

The bucket membership requires **both** a submission timestamp and a return
event timestamp, with stable task-to-batch identity. A current task status
or an unrelated `updated_at` timestamp is not submission evidence.

`total_submitted_video_seconds = new + old_rework + same_day_rework`

The current chart plots each user's total submitted VIDEO duration as a connected
line and places Old Rework and Same-day Rework as separate lollipops.
The two rework values are subsets of the line total, not extra hours. New
video duration is the remaining difference and is included in the line.
When the source is only a submitted-status snapshot, no such classification
is asserted and no rework lollipops are drawn.

The existing Daily Report's legacy `Total Duration` excludes old rework
(it is `new + same-day`). The new lollipop intentionally uses the complete
three-bucket total. Neither version is actual page time.

## API research and limits

The published upstream `/openapi.json` has 350 routes. Authenticated,
read-only GitHub runner tests established:

| Endpoint | HTTP | Relevant available evidence |
| --- | --- | --- |
| GET /api/dashboard/annotator-efficiency | 200 | per-user submitted, completed and rework **video durations** |
| GET /api/dashboard/overview | 200 | summary duration metrics, some based on current status |
| GET /api/dashboard/overview/hourly | 200 | **worklog** activity and completed-hour attribution; not payable submitted-duration split |
| GET /api/slice/tasks | 200 | task ID, current status, video duration, updated_at; no actual submitted_at in list |
| POST /api/tasks/assigned/overview | 200 (authenticated own ID) | task ID, current status and prior_return_count; no actual submitted_at in list |
| GET /api/review/reviewed-tasks | 200 | per-task review decision and reviewed_at |
| GET /api/review/reviewed-batches | 200 | per-batch review decision and reviewed_at |
| POST /api/tasks/overview | 403 | contains actual slice_submitted_at, but denied to configured Collector account |
| GET /api/dashboard/user-activity | 403 | activity report denied; not required for payable video duration |

Aggregate `submitted_duration_seconds` is useful as a control total
**only after its status and date semantics are verified**. It does not
independently split old from same-day rework. `prior_return_count` confirms
some past return evidence, but not its date relative to today's submission.

The original Daily report source uses `slice_submitted_at` and returns/
review events to classify each submitted task. The retained daily-work
collection stops at October 13, and the configured account currently
gets 403 from the authoritative task-overview source. Therefore the chart
must say **Unavailable** for unverified submission categories, not convert
the available 2026-11 return *events* or current batch status into paid output.

## Recovery route

Investigate a properly authorized read-only task-submission history route,
such as upstream task state-transition/data-flow details, with task ID,
actual submission timestamp and submitted video duration. Join it to the
already captured batch-return and reviewed-task histories. Validate selected
users, India-local date boundaries, deduplication, repeated returns,
and reconciled totals.

If only an aggregated submitted-duration measure is available, display it
as a distinct **aggregate payable-video candidate with unclassified split**,
not as invented New/Old/Same-day portions.

No screen-time tracking is requested or planned as part of this dashboard.
No upstream write endpoints, payment values or production data were changed.

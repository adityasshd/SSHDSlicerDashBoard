# Daily and User Report diagnosis — 29 October 2026

The pages render from saved reports, but the configured store has no submission
captures after **13 October 2026**. In the current 30-day window, only October
5–13 have recorded daily submissions. A missing capture remains unavailable,
rather than becoming a zero-work day.

A read-only upstream check authenticated successfully, then received **HTTP 403**
from `POST /api/tasks/overview` with code `TASK_POOL_ADMIN_REQUIRED`. The response
states that only administrators may access the task pool. The configured account
therefore cannot collect the task submission timestamps used by these reports.
Repeated login does not resolve this permission failure.

The follow-up account audit verified `GET /api/auth/me`: the configured source
login has **role 5 (Leader)**. The effective dashboard configuration and the
dashboard, analytics, and scorer `.env` files all resolve to the same upstream
username/password pair. The retained upstream frontend maps Admin to role 6 and
Super Admin to role 1. The denial explicitly asks for an administrator; it does
not establish that Super Admin is required. A role-6 account has not yet been
tested in this audit.

`SLICER_ADMIN_PASSWORD` is used by the local settings/mapping unlock check. It is
not sent to `/api/auth/login` and has no separately configured upstream username.
The collector's upstream login uses `ADMIN_USERNAME` and `ADMIN_PASSWORD`.
No additional account is needed if an existing authorized upstream Admin login
is available; its configuration location must first be identified and verified.

The saved collector health entry is also overdue: its last recorded daily
attempt is October 8 and is marked failed. This health entry is older than some
retained reports, so it does not establish the exact date collection stopped.
The Vercel viewer intentionally reads saved data and does not run collection.

Both Daily and User Report content builders successfully rendered and serialized
the configured saved data during this check. The missing current data explains
their unavailable KPIs and gaps in the charts; it is not a missing page route.
The documented cPanel and Vercel URLs returned 403 and 402 respectively from this
environment. These hosting responses do not identify the URL currently being
used by the user. Interactive browser verification was unavailable.

## Local changes

- Add a separate **New submissions** line to the main trend. It uses first-time
  submitted video duration and is included in Total Work Done. Person filters,
  recorded zeroes, and missing-date gaps follow the existing daily reports.
- Explain missing captures and show the latest recorded submission day on the
  report pages and main trend.
- Make return feedback counts explicit: distinguish return events from reason
  mentions, show segment counts and return totals, and use actual return events
  as the denominator in hover percentages. Categories are labeled as automatic
  groupings of reviewer notes. Empty notes have their own category.
- Deduplicate return event IDs, filter return dates in India time, use current
  account mappings, and keep viewer refreshes from attempting upstream reads.
- Report the specific task-inventory permission requirement without a redundant
  re-login when the source returns `TASK_POOL_ADMIN_REQUIRED`.

## Restoring fresh submissions

1. Configure the external collector with an authorized source administrator
   account that can access the task inventory. Keep credentials in its existing
   environment configuration.
2. On that collector, with `DASHBOARD_ROLE=collector` and `VERCEL` unset, run
   `slicing-dashboard data-refresh --source daily` against the same shared store.
3. Check the daily source in `slicing-dashboard data-refresh --health-only`, then
   resume the collector's schedule and refresh the viewer.

The daily refresh captures today and reconciles yesterday. It cannot manufacture
the unobserved intervening daily history from the latest task state. Recover
older dates only from verified retained submission evidence.

No source permissions, credentials, schedules, deployments, or remote report data
were changed by this diagnosis. The chart changes remain local.

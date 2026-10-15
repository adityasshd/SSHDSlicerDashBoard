# Vercel saved-data deployment

`main` deploys the dashboard only. A separate collector will poll the source API
on cPanel and publish retained results into the same database. The collector
repository and cron setup are a separate task; this change does not activate them.
Until that worker runs, the viewer shows existing captures with their timestamps,
or unavailable data. It does not manufacture missing history or verified zeros.

## Import settings

- Git repository: `adityasshd/SSHDSlicerDashBoard`, production branch `main`.
- Framework preset: **Flask**; root directory: **`./`**.
- Leave Build Command, Install Command, and Output Directory at their defaults.
- Python: **3.12**, selected consistently by `.python-version`, `pyproject.toml`,
  and the checked-in `uv.lock`. Vercel currently supports 3.12, 3.13, and 3.14.
- `vercel.json` uses the Flask preset, without legacy `builds`/catch-all routes.
  `app.py` exports the Flask WSGI application. Its maximum request duration is 30s.

The reported build failed because `.python-version` requested unavailable 3.11
even though the Vercel builder selected 3.12. The version/lock changes resolve
that mismatch. A live Vercel build is still required to verify the Linux bundle.

## Environment variables

Keep these in Vercel's environment settings, never in source control:

| Variable | Viewer purpose |
| --- | --- |
| `MONGO_URI` | Shared retained reports/configuration; recommended existing backend |
| `DATABASE_URL` | Supported PostgreSQL alternative; do not configure a different data store accidentally |
| `DASHBOARD_URL` | Existing source identity, matching the collector exactly; not the Vercel website URL |
| `ADMIN_USERNAME` | Existing source account identity; must match the collector for scoped snapshot keys |
| `SLICER_ADMIN_PASSWORD` | Existing settings/mapping editor password |
| `TIMEZONE` | `Asia/Kolkata` |
| `CRON_SECRET` | Authentication for health/storage diagnostics; not a scheduler activation switch |

`ADMIN_PASSWORD` is unnecessary for the Vercel viewer. It belongs on the future
collector. `VERCEL` automatically enforces viewer mode, even if someone sets
`DASHBOARD_ROLE=collector` in Vercel. For local viewer testing, set
`DASHBOARD_ROLE=viewer`. Management edits and marking inbox messages read still
write their existing records; source capture/snapshot publication is disabled.

If the read-only reports use a database account without write permissions,
management editing and marking inbox items read will be unavailable.

## What prevents repeated compute

- No Vercel cron, Node dispatcher, or self-calling capture chain is deployed.
  `.vercelignore` excludes the legacy API functions and server dispatcher.
- All three browser timers are disabled: five-minute refresh, heartbeat, and
  one-minute workflow ingestion. Refresh/page navigation read saved evidence.
- Panel/trend callbacks do not schedule live capture follow-ups. Daily Report
  does not launch a current/yesterday inventory reconciliation. Completion and
  efficiency use retained captures; workflow reads skip ingestion/projection.
- The scraper's HTTP request hook rejects upstream requests before transport,
  providing a second guard if an interactive path accidentally requests a scan.
- Authenticated capture/job endpoints return 410 before creating collector
  services. Read-only health checks do not reconcile/write job checkpoints.
- The viewer cannot publish dashboard snapshots over the collector's data.
- Warm instances reuse the saved dashboard snapshot for 60 seconds. One manual
  Refresh's parallel callbacks share a database reload within a two-second window.
  Database read failures retain the previous capture and show a warning.
- CSS/JS/favicon assets are copied to `public/assets` during the build and served
  by Vercel's CDN. Versioned Dash component scripts are CDN-cacheable. Report JSON
  remains private and is never placed in the shared cache.
- Local data, logs, tests, virtual environments, and collection entrypoints are
  excluded. Matplotlib is installed only with the optional analysis extra.

Saved dashboard panels are scoped to their source identity, mappings, and date
range. The collector must publish those exact scopes. Arbitrary date ranges with
no prepared panel show unavailable rather than starting an upstream scan. Daily
and User Report history use the existing compact daily chart records. Completion
requires the saved exact-range completion capture. User batch lists use a richer
saved `user_batches[date]` packet if present; otherwise they show known assignments
and explicitly flag that the worked-on batch list is incomplete.

## Collector data contract for the next repository

Use the existing database/collection formats, not a second independent database:

- Dashboard snapshot: existing `dashboard_snapshot/latest-compressed-v1` format,
  with `cache`, `dashboard_panels`, `last_sync_time`, batch/return ledgers, and
  exact-range completion items. PostgreSQL uses its existing snapshot key.
- Daily reports: existing `daily_work_reports` and compact chart projections.
- Workflow/approvals/efficiency: existing scoped `workflow_records` formats.
- Account mappings and settlement periods: existing shared configuration records.

Source identity, canonical mapping, timestamps, pagination checks, and evidence
merging must remain consistent with this repository. Cron should invoke that
collector directly, not an HTTP endpoint on Vercel. Disable the old cPanel web
application separately when ready; this repository change does not stop it.

## Verification and usage budget

1. Deploy the updated `main`, then verify the build uses Python 3.12 and the
   locked production dependencies. There should be one Python dashboard function
   and no deployed Node capture function or cron.
2. Open Dashboard, Daily Report, User Report, Workflow, and Settings. Check known
   saved totals/timestamps; missing scopes must say unavailable.
3. Click Refresh after the collector publishes a new capture. Check the saved
   values update. Refresh does not collect new source evidence itself.
4. Leave an open tab idle and confirm there are no recurring Dash POSTs or source
   heartbeat calls. Check authenticated capture endpoints return 410.
5. Monitor Vercel CPU, memory duration, transfer, and invocations daily after launch.
   Disable old external cron requests aimed at Vercel; rejected requests still
   incur function invocations.

The supplied previous totals were 12h 1m CPU against 4h, and 754.1 GB-hours memory
against 360. These need reductions of roughly 67% and 52% respectively merely to
fit those allowances. For a 30-day month, the allowances average **8 CPU minutes
and 12 GB-hours per day**, across the team; target substantially below that to
leave room for traffic and other projects. A 30-second request timeout limits a
single invocation, not total monthly consumption.

As an illustration, a 206-second scan every five minutes is 16.48 function-hours
per day. At 2 GB that is about 989 GB-hours over 30 days for just one continuously
invoked function. A Node dispatcher waiting on a Python collector can add another
active instance. Moving collection off Vercel removes this workload, but browser
traffic, chart computation, cold starts, and database latency still count. No local
change can guarantee a monthly quota without measuring production traffic.

An already paused team may remain paused until its allowance resets or Vercel
resolves the restriction. Importing another project does not establish a fresh
independent team allowance. Check the team's actual reset/resume status before
switching the domain.

References: [Python versions](https://vercel.com/docs/functions/runtimes/python/python-version),
[Flask deployments](https://vercel.com/docs/frameworks/backend/flask),
[Fluid CPU/memory billing](https://vercel.com/docs/functions/usage-and-pricing),
[Hobby limits](https://vercel.com/docs/plans/hobby).

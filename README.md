# SSHDSlicerDashBoard

## Vercel deployment (saved-data dashboard)

The `main` branch deploys a Python **3.12** Flask/Dash viewer on Vercel. It reads
retained reports from MongoDB/PostgreSQL and does not scrape the upstream API.
Collection must run separately, writing the same database. Refresh reloads saved
data; background browser polling and Vercel cron/dispatcher functions are disabled.
Missing captures remain unavailable until the collector publishes them.

Import the repository with **Flask**, root directory **`./`**, and the default
build/install settings. See [Vercel setup and compute limits](docs/vercel-deployment.md)
for environment variables, storage requirements, and verification. Dependency
versions are recorded in `uv.lock`; matplotlib is an optional analysis dependency.

Video Slicing Dashboard — a scraping, data processing, and reporting system built with Dash.

## Features

- **Interactive Dashboard** — Plotly Dash-based web UI with Bootstrap styling
- **Data Scraping** — HTTP-based scraper for extracting slicing data
- **Data Processing** — Cleaning, normalization, and aggregation pipelines
- **Reporting** — Automated weekly report generation
- **Database** — PostgreSQL-backed storage via SQLAlchemy
- **CLI** — Command-line interface for data operations

## Tech Stack

- Python 3.11+
- Dash / Plotly / Dash Bootstrap Components
- Pandas / NumPy
- SQLAlchemy + PostgreSQL (psycopg2)
- Pydantic / Pydantic Settings
- httpx / BeautifulSoup / lxml

## Setup

```bash
# Clone the repo
git clone https://github.com/adityasshd/SSHDSlicerDashBoard.git
cd SSHDSlicerDashBoard

# Create virtual environment and install dependencies
uv sync

# Copy environment config
cp .env.example .env
# Edit .env with your database credentials and API keys

# Run the dashboard
PYTHONPATH=src uv run python src/slicing_dashboard/app.py
```

On Windows, the local runner keeps debug tools enabled but disables automatic process/browser reloading to avoid Werkzeug's `WinError 10038` socket failure during reload. Restart the server after Python changes, then refresh the browser. In PowerShell, start it with `uv run python -m slicing_dashboard.app`.

## cPanel deployment

These instructions describe the older combined application. The separate cPanel
collector is a subsequent deployment task; do not schedule requests to the Vercel
viewer to perform collection.

Use **Setup Python App** with **Python 3.12**, production mode,
and the project folder as the application root. The requirements target Linux x86_64 with glibc
2.28 or newer (for example, CloudLinux 8/9).

1. Upload the project, including `src/`, `config/`, `requirements.txt`, and
   `app.py`, and `passenger_wsgi.py`. Keep `.venv/` and `node_modules/` on your local machine.
2. Use a domain/subdomain with the application URL at `/`; dashboard links assume
   the application is served at the domain root.
3. Set **Application startup file** to `app.py` and **Application entry point**
   to `application`. The root wrapper exposes the dashboard's Flask WSGI server.
   This avoids a hosting-generated `passenger_wsgi.py` wrapper targeting itself.
   Hosts that load a custom WSGI file directly can also use the repository's
   `passenger_wsgi.py`, which contains `from app import application`.
4. Add `requirements.txt` to the configuration files and click **Run Pip Install**.
   Alternatively, activate the virtual environment using the command cPanel shows,
   then run:

   ```bash
   python -m pip install -r requirements.txt
   python -m pip check
   ```

5. Set the environment variables from `.env.example`, including `ADMIN_USERNAME`
   and `ADMIN_PASSWORD`, or create `.env` in the application root. Configure
   `MONGO_URI` or `DATABASE_URL` if using a remote database. Keep `data/`, `config/`,
   and `logs/` writable by the application user; upload existing retained data
   when migrating an installation.
6. Restart the application from cPanel. Passenger serves the Flask server exposed
   by Dash, so no separate `app.run()` command is needed.

If Save or Restart reports `No such application (or application not configured)
"dashboard_app"`, return to the Setup Python App application list and reopen the
registered application. Its root should be `dashboard_app` (relative to the
account home directory), not an application URL. Uploading the folder alone does
not register a Python application. If there is no matching application, use
**Create Application** with the settings above. If a matching application exists
but still cannot be saved or restarted, ask the hosting provider to check its
CloudLinux Python Selector registration and Passenger configuration, including
ownership of `/home/ipsutpvq3gsk/.cl.selector/htaccess_cache` and the domain document
root permissions. CloudLinux documents this exact cPanel restart error in
[Unable to restart Python applications](https://cloudlinux.zendesk.com/hc/en-us/articles/10262954969628-Unable-to-restart-Python-applications).
Preserve the application files, `.env`, and retained data while the registration
is repaired.

When the domain document root is `/home/ipsutpvq3gsk/dashboard_app`, its Passenger
configuration belongs in `/home/ipsutpvq3gsk/dashboard_app/.htaccess`. Prefer the
configuration generated by Setup Python App. If that file was emptied, use
[the recovery example](docs/cpanel-passenger.htaccess.example) after confirming
that `PassengerPython` matches the actual cPanel virtual environment's `bin/python`
path (the environment directory normally uses `3.11`, not `3.11.16`). The example
also blocks direct HTTP access to credentials and local source/data directories
because the document root contains the application files. Existing rewrite rules
and cPanel-managed environment-variable blocks must be preserved when restoring
an existing file. `.htaccess` stays Git-ignored so repository deployments do not
overwrite the hosting configuration. Restoring these directives does not repair
incorrect Selector cache ownership or document-root permissions; those still
require the hosting provider if the same error persists.

If the Passenger log repeats `imp.load_source('wsgi', 'passenger_wsgi.py')` until
`RecursionError`, the server's wrapper is loading itself. Set the Selector startup
file to `app.py`, keep the entry point `application`, and save. If the `.htaccess`
file specifies `PassengerStartupFile`, it should also be `app.py`. Inspect the
generated wrapper afterwards: it must load `app.py`, or simply import
`from app import application`. Restart and inspect only the newly appended log
entries; old tracebacks remain in the log after a successful repair.

If startup fails with `OpenBLAS blas_thread_init: pthread_create failed` while
importing pandas/NumPy, the hosting account cannot allocate the requested numeric
library threads. The package sets single-thread defaults before numeric imports.
Explicit hosting environment values are respected, so set `OPENBLAS_NUM_THREADS`,
`OMP_NUM_THREADS`, `MKL_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` to `1` in Setup Python
App if the account already supplies higher values, then save and restart. These
variables must be available before Python imports NumPy; `.env` alone is loaded
too late to override an already initialized BLAS runtime. See
[OpenBLAS runtime variables](https://www.openmathlib.org/OpenBLAS/docs/runtime_variables/).

Report/API read pools now default to at most two workers and continue inline if
the operating system rejects a thread start. For a constrained cPanel account,
set `DASHBOARD_MAX_WORKERS=1` to perform those reads sequentially without creating
report worker threads. Independent page callbacks remain available; reads can
take longer when serialized. This reduces thread demand but does not increase
the hosting account's quota or prove MongoDB connectivity.

For a working live dashboard with missing periods, unmapped accounts, or gaps in
the trend, verify the saved store separately. `.env` is loaded from the project
root; existing cPanel environment variables override its values. `/api/storage-health`
uses the same `Authorization: Bearer CRON_SECRET` protection as `/api/data-health`
and returns configuration presence, an eight-second-bounded MongoDB ping,
collection counts, and the retained daily date range. It does not return the URI,
credentials, raw exception messages, or report rows, and does not write data or
create indexes. It also reports when the environment's `MONGO_URI` differs from
the file. A ready result confirms readable saved configuration/history; missing
collections require checking the selected database or migration. A connection
failure requires checking Atlas network access and the hosting server's outbound
connectivity. See [MongoDB Atlas connection troubleshooting](https://www.mongodb.com/docs/atlas/troubleshoot-connection/).

See [cPanel's Python Selector setup](https://support.cpanel.net/hc/en-us/articles/360057849753-How-to-register-an-application-with-Python-Selector)
and [Python WSGI deployment documentation](https://docs.cpanel.net/knowledge-base/web-services/how-to-install-a-python-wsgi-application/).

## Workflow history and shared inbox

Open `/workflow` for persisted batch actions, return cycles and explicitly labeled synthetic approval prerequisites. A completed batch implies Leader, Auditor and Admin approval under the configured business rule; missing review times and reviewer identities remain unknown. New source evidence supersedes synthetic entries while retaining projection history.

The navigation bell shows the latest ten sampling/rework notices, with a full unread count and persistent shared read state. Its source is `/api/requests`; upstream request status is independent of local read/unread. Source evidence and inbox state use configured MongoDB/PostgreSQL, with SQLite for local installations without a configured database. Collection occurs during application refreshes.

To resume a bounded history scan:

```bash
uv run slicing-dashboard workflow-sync --backfill --max-rounds 5
```

Remaining cursors resume on later refreshes; available API history may be incomplete. Synthetic milestones are excluded from daily approval hours because their actual event times are unknown. See [workflow policy and implementation](docs/batch-workflow-plan.md).

The dashboard trend is an area chart. Dated Leader/Auditor/Admin batch approvals use batch video duration at capture as an explicitly labeled estimate; task-level review logs and undated synthetic milestones do not add hours. The current assigned/rework chart reads fully paginated task-status queues, independently of settlement dates and historical batch totals. Queue captures expire after 60 seconds and manual/automatic refresh bypasses them. A failed queue read displays an unavailable/incomplete message.

Assignment dates and age colors use the original timestamp, exact batch/legacy-return links, or an account's unambiguous active batch date. Account-level dates are labeled in the hover; ambiguous dates remain Unknown. Batch totals never create extra assigned hours.

Open `/settings` for Settlement periods and User mappings. Both editors retain unsaved changes across tab, theme and page changes. The dashboard removes the bottom Slice Data Overview and Settlement Overview tables and management tabs.

The inbox also records Admin batch approvals/completions and batch returns by any reviewer. Completion without a dated Admin action is explicitly labeled inferred. New recent events show in-app pop-ups; history imports do not replay as pop-ups. Notifications poll every minute while the application is open, retain their read state, and offer individual history links and Mark all read.

Daily Report has redesigned output/composition cards, grouped charts, and a per-person comparison with the previous day. User Report includes a 90-day activity calendar: grey means no recorded capture, while recorded zero output has its own color. Both additions use retained evidence without extra API calls.

Total daily work is **new work + same-day rework**. Old rework remains visible separately and is excluded from work totals, day comparisons, daily trends, activity calendars, recorded scope sums and averages. Rework share uses same-day rework divided by this total; the work-breakdown donut follows the same definition. Saved summary rows are recalculated on read without rewriting retained evidence.

Report routes share a prepared payload for up to 60 seconds; manual/automatic Refresh bypasses it. The dashboard legend and trend load independently of aggregate/queue callbacks, and graphs resize when a hidden page becomes visible. Failed workflow polls retain the last known approval evidence with an error message. Unchanged workflow evidence skips projection writes.

User Report presents eight cards, including completed video duration and task count for the current settlement date range. Completion uses the efficiency API's current completed status, independently of daily submissions; it does not reconstruct approval times for historical dates. Completion captures are reused for 60 seconds and remapped when user mappings change. Failed or incomplete completion reads show unavailable data. The activity calendar and individual trend share equal desktop columns and stack on mobile. All User Report graphs have explicit container heights to prevent Dash's default `height: 100%` from extending below their section headings.

Pending Review loads independently from fully paginated current task queues, with targeted refresh, mapping/workflow invalidation, a 60-second reuse limit, and protection against older requests finishing last. Tooltip account IDs are scoped to the contributing review/work stack. User Report batches include assignments and recorded work on the selected date. See [chart correctness and verification](docs/dashboard-chart-audit.md).

Daily Report renders recorded figures first, then verifies today/yesterday in a separate live callback. The saved report is labeled during verification; date/refresh guards prevent older captures replacing a newer selection. Historical dates use saved evidence directly.

Daily Report reconciles yesterday against the current submission source on entry and Refresh, retaining already observed tasks and adding later submissions. An afternoon capture no longer becomes the final daily total at midnight. Work and comparison charts use the same per-person totals and include the same zero-output roster.

Collection code remains available for an external worker through
`slicing-dashboard data-refresh`. On Vercel, capture/job endpoints return **410**
after authentication; `/api/data-health` and `/api/storage-health` remain protected
diagnostics. The old combined deployment is documented in
[data recovery](docs/data-recovery.md); its Vercel scheduler instructions are historical.

Current assignable video duration and task count come only from
`/api/slice/pool-inventory`, summing the normal and urgent unassigned pools. A
verified empty pool displays zero; failed or invalid captures display unavailable.
Historical overview/funnel values do not override this inventory.

## Project Structure

```
src/slicing_dashboard/
├── app.py              # Dash web application
├── cli.py              # Click CLI
├── config.py           # Configuration & settings
├── data_manager.py     # Data fetching & caching
├── db.py               # Database connection
├── assets/             # Static assets (CSS, images)
├── extraction/         # Data extraction logic
├── models/             # Pydantic / SQLAlchemy models
├── processing/         # Data cleaning & normalization
├── reporting/          # Weekly report generation
└── scraper/            # HTTP scraper
```

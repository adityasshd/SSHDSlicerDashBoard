# Submission tracking from 25 November 2026

The main Dashboard prefers verified dated daily reports. When those are
unavailable, dates from 25 November onward use durable observations from
`GET /api/slice/tasks`. The old submitted-status inventory is no longer shown
as today's output. The UI displays the recording start and last update in IST.

The first complete cursor scan establishes a baseline. A task contributes once
per India-local day when the same assignee is observed first in assigned,
slicing or rework status and later in submitted/review/completed status. Both
observations must fall on that day. Initial submitted stock, unknown first-seen
tasks, reassignment, overnight intervals and subsequent approvals add no work.
Task `updated_at` reduces later inventory scans; it never dates a submission.

This is observed output, with partial coverage. Activity before the baseline,
entire cycles between polls, and transitions crossing midnight are not
reconstructed. The fresh/old/same-day rework split stays unavailable. No screen
time, worklog time, inventory delta or synthetic submission is added.

`submission-observation` records use insert-once account-scope/task/day IDs.
They survive approvals, restarts and retries. The `submission-tracking`
checkpoint is published only after a complete validated read and event writes.
A shared lease serializes collectors. The viewer reads saved data only.

Run once, or poll every minute on this computer:

```powershell
.venv/Scripts/python.exe scripts/track_submissions.py
.venv/Scripts/python.exe scripts/track_submissions.py --watch --interval 60
```

Local status is `data/reports/submission-tracking-status.json`. A local watcher
requires this computer and process to remain running. The external collector
has a `submissions` source for durable hosted polling; deploy that code before
relying on its schedule. Existing dashboard capture schedules are unchanged.
Efficiency history refreshes start on the new tracking date; saved older
efficiency reports remain readable.

## Historical preservation and cleanup

`scripts/archive_history.py` exports every retained collection to BSON gzip
files with index metadata. These are compatible with MongoDB Database Tools'
directory restore format. Each document is decoded, re-encoded and checked
against its original BSON bytes; collection counts and SHA-256 digests are
recorded. This verifies archive integrity, not an isolated database restore.
The export is not an atomic point-in-time backup of concurrent writers.

The archive includes per-month and per-cycle saved batch summaries, daily
capture dates, original settlement settings and reconstruction drafts. Period
summaries describe retained status at export time; they are not certified final
settlement values and never replace a validated closure snapshot.

Deletion is restricted to archived, superseded pre-cutoff workflow versions:
observations, batch observations and projection history. It retains the latest
version per real event/batch identity, timestamp ties, and all observations
referenced by current projected events. Exact ID/kind/payload predicates protect
concurrently changed records. Current events, return evidence, reports, base
ledgers, notifications, checkpoints, mappings and settlement settings remain.
No automatic expiry or recurring deletion is installed.

```powershell
# Export and inspect eligible versions without deleting.
.venv/Scripts/python.exe scripts/archive_history.py --before 2026-11-25 --output data/backups/history-start-2026-11-25
# Re-verify the export, retain its manifest/periods in history_archives, and prune.
.venv/Scripts/python.exe scripts/archive_history.py --before 2026-11-25 --output data/backups/history-start-2026-11-25 --reuse-verified-export --apply
```

Preserve the entire archive folder. To recover old versions, restore its BSON
directory into an isolated database using a securely configured mongorestore,
inspect the desired documents, and insert only missing version IDs. Do not use
`--drop` against the live database: it would remove newly recorded work.

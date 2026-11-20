# Slicer — MongoDB storage and submitted-duration audit

**Audited:** 20 November 2026 (Asia/Kolkata)  
**Atlas project:** SSHD_Slicer / cluster `Slicer` (Free tier, AWS `AP_SOUTH_1`)  
**Databases:** `slicing_dashboard` and `Slicer_Analytics`  
**Source:** live read-only MongoDB statistics, collection counts, and selected record metadata; deployed GitHub repository `adityasshd/SSHDSlicerDashBoard`, `main` at `1c49da84`.

## 1. Storage / quota risk

| Database | Logical data bytes | Index bytes | Objects |
|---|---:|---:|---:|
| slicing_dashboard | 495,764,218 | 25,595,904 | 231,745 |
| Slicer_Analytics | 2,073,890 | 532,480 | 2,274 |
| **Total** | **497,838,108** | **26,128,384** | **234,019** |

Logical data + index bytes: **523,966,492 bytes (~499.69 MiB)**. Against an indicative 512 MiB Free-tier storage ceiling, this is approximately **97.6%** used, leaving **~12.31 MiB**. Verify the precise quota reported by Atlas; don't confuse this with compressed physical storage (~101 MiB across both DBs).

Main candidate for archival review: `slicing_dashboard.workflow_records`: **197,347 records, ~441.95 MiB of logical document size**. Record-kind counts:

| Kind | Documents |
|---|---:|
| observation | 69,704 |
| batch-observation | 56,521 |
| projection-history | 55,361 |
| event | 13,867 |
| notification | 870 |
| notification-read | 864 |
| efficiency-capture | 142 |
| remaining operational kinds | 18 |

This is *not* a list of records safe to delete. Historical approvals, return evidence, and workflow projections may be needed for auditability and the historical dashboard. The four `settlement_snapshot_drafts` (July–October) each explicitly say `safe_for_raw_deletion: false`, with incomplete final-hour/individual-history coverage.

## 2. Submitted video duration: confirmed causes

The `today-submissions-lollipop` chart uses **daily, dated, verified video submission duration** from `daily_work_reports`; its fallback is a **same-day efficiency capture**, clearly labeled as current submitted-task *status*, **not** proof of submissions made today. It never substitutes screen/worklog time.

**Live evidence:**

- `daily_work_reports`: **9 rows**, dated **Oct 5–Oct 13, 2026**; **none** dated Nov 20.
- `workflow_records` with `kind=efficiency-capture`: **initial check** found 142 rows, latest `display_date=2026-11-19`, and 0 for Nov 20. **Later on Nov 20 at 06:40 UTC, a new Nov 20 capture arrived.** The initial missing-today statement is no longer current. This still does not restore the separate verified daily submission reports.
- `data-health` saved status: daily source failed with `DailyCaptureFailure`, `failure_reason=task_overview_forbidden`; `last_success_at` for daily source was Oct 8 and its most recent saved attempt was Nov 17.
- Saved refresh jobs recorded `DailyCaptureFailed:today:task_overview_forbidden` and `DailyCaptureFailed:today:task_inventory`.
- Upstream API contract in `docs/today-submissions-work-hours-contract.md` confirms `POST /api/tasks/overview` returns 403 for the current collector, while it is the known endpoint containing `slice_submitted_at`. `GET /api/slice/tasks` supplies current status and video duration but not verified submitted-at timestamps. Thus return notices and current statuses cannot produce an honest New/Old/Same-day payout split.

**Conclusion:** The chart is missing verified input, not simply misformatting a duration. The daily-capture collector needs authorized read-only access to actual task submission timestamps (or an alternative approved endpoint containing task ID, submission timestamp, duration, and stable batch ID). The Nov 20 fallback capture must also be scheduled successfully. Never relabel status-stock duration as today's submitted work.

## 3. Immediate safe execution sequence

1. **Take an external BSON backup** of both databases before any deletion. MongoDB Atlas Free clusters do not offer the same on-demand backups as paid dedicated tiers. Use the accompanying `slicer_mongodb_backup.py` on a computer that already has the MongoDB URI; never send the URI/password in ChatGPT.
2. **Keep the archive outside the Git repository**, encrypted and access controlled. Review the generated `manifest.json`, SHA-256 digests, document counts and index names. A successful dump **is not** a fully verified restore or a point-in-time consistent snapshot if the application continued writing.
3. **Restore into an isolated test MongoDB deployment** with enough storage, compare source/archive counts and key reporting computations, and explicitly authorize any deletion only after that passes.
4. **Inventory `workflow_records` dependencies**: distinguish immutable evidence/event records, current projections, reversible observations and true caches. Validate reconstructed current state and settled period reports. Archive qualifying IDs externally; do not add a blind TTL or delete all old records.
5. **Repair collector permissions and scheduled evidence**. First test a read-only `/api/tasks/overview` request under an approved account. Confirm a dated submission report is persisted for Nov 20, and that current-day efficiency capture is available. Only then validate the submitted-hours chart against upstream videos and return timestamps.
6. Run regression tests for settlement, submitted-hour totals, rework classification and chart rendering after any approved changes.

### Running the backup script (Windows PowerShell)

Install MongoDB Database Tools so `mongodump.exe` is on PATH, then from the repo root (which contains `.env` with `MONGO_URI`, or with that variable already available in the shell):

```powershell
python scripts\slicer_mongodb_backup.py --output "D:\SlicerBackups" --dry-run
python scripts\slicer_mongodb_backup.py --output "D:\SlicerBackups"
```

If using the provided standalone script rather than a checked-in copy, replace `scripts\slicer_mongodb_backup.py` with its downloaded location. The script does not drop, modify or write any source database records. It generates two compressed archives and one audit manifest. It **does not** restore or purge anything.

## Current execution status

- [x] Read-only quota audit, highest-volume collection identified.
- [x] Submitted-duration source and permission failure independently confirmed in source records and implementation.
- [x] Standalone backup script written, syntax-checked and basic safety helpers tested locally.
- [ ] Actual `mongodump` archive of the live cluster: **not executed**; this session has no MongoDB URI credentials or Database Tools binary.
- [ ] Restore verification: **not executed**.
- [ ] Cleanup: **not authorized / not executed**.
- [ ] Today's dated submitted-duration ingestion: **not restored**; requires approved upstream task inventory access and a functioning collector.

**Safety:** Do not use free-tier remaining capacity to copy entire archives or historical collections inside the same MongoDB cluster.

## 4. Completed Hours not updating — November 20 follow-up

**Production:** Office Vercel project \`sshd-slicer-dash-board\`, production deployment of \`main\` at \`1c49da84\`. \`runtime.viewer_mode()\` is true in Vercel. Browser callbacks intentionally **never collect upstream data**; even the Refresh button reloads only the last MongoDB \`dashboard_snapshot\`. Auto polling is disabled to control hosting costs. An independently running external collector must publish refreshed panels.

**Two separate completion paths:**

- The *historical completed-hours trend* is built from \`workflow_records\` daily \`efficiency-capture\` source-status records. A new Nov 20 record was saved at approximately **2026-11-20 06:40:26 UTC**. These captures use date-filtered status metrics; they must not be misrepresented as admin approval timestamps.
- The Dashboard *Completed Hours KPI* and *Completed Duration* plot read a separately captured, exact-range **completion panel** in \`dashboard_snapshot.dashboard_panels\`. This panel is built by \`capture_panel(manager, 'completion', start, end)\` and receives source \`get_user_breakdown_df\`, not directly from the dated \`efficiency-capture\` record. Recording a new efficiency day does **not** automatically rebuild that panel.

**Live evidence:** The compressed MongoDB snapshot document \`latest-compressed-v1\` had an updated timestamp of **2026-11-20 12:11:11** (collector/server-local format). Its **individual completion packet** time was not yet known from Atlas metadata alone; the binary compressed snapshot must be decoded before claiming the KPI itself is current. The saved \`data-health\` status and \`refresh-job\` records were still dated **Nov 17**: last successful \`efficiency\`, \`completion\`, and \`chart_panels\` health phases at that time. Thus normal scheduled collector health is stale even though direct efficiency history captures and snapshot writes have occurred later.

Vercel logs also report occasional **30-second \`/flask\` timeouts**. These may interrupt responses but are *not* established as the cause of a particular missing Completed Hours update.

**Next exact diagnosis:** Run the safe script added in this PR on the configured collector/development machine:

\`\`\`powershell
python scripts\audit_completed_hours_freshness.py
\`\`\`

It reads the existing compressed snapshot and the latest dated efficiency capture. It prints only panel timestamps, availability, anonymized panel-key prefixes, counts and their freshness gap. It does not write to MongoDB, scrape tasks, or show per-user durations. If the latest saved completion panel predates the latest source capture, fix the external collector's **completion/chart_panels publication**. If the packet is fresh but the browser remains stale, use the Vercel Refresh button once to reload the MongoDB snapshot, then investigate viewer cache/request timeouts. **Do not add automatic Vercel upstream scraping or cost-heavy polling to hide the collector fault.**

**Safety:** No completion-hour totals should be inferred from \`batch_returns\`, original batch duration, raw status history, or work-session time. First verify matching user mappings and exact report period.

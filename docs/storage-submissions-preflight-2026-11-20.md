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
- `workflow_records` with `kind=efficiency-capture`: **142 rows**, latest `display_date=2026-11-19`; **0** for Nov 20 (and 1 for Nov 19).
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
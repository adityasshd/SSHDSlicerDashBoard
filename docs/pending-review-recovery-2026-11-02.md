# Pending-review recovery — 2 November 2026

The local dashboard now renders the verified current review workload. At the
live chart check, Auditor review contained **256 tasks / 06:54:31**, including
**70 Aditya tasks / 01:00:17**. Leader review contained 36 tasks / approximately
01:35:13. Admin review contained no task-level queue records. These are current
captures, not a reconstruction of Friday's complete cohort.

## Changes

- Keep current task queues authoritative for membership, owner, and review stage.
- When a queue duration is zero or missing, fetch time ranges for those exact
  task IDs through the fully paginated assigned-task overview, using the
  authenticated account's own ID from `/api/auth/me`.
- Check task ID, slicer ID, and current status before accepting `end - start`.
  If the role-specific overview omits an ID, read that exact task's detail with
  the same session. Missing, changing, invalid, or incomplete evidence makes the
  capture unavailable instead of fabricating zero hours.
- Preserve the original queue duration and the timing endpoint as recovery
  provenance in exported task records.
- Version the pending-panel cache identity so captures made with the old
  zero-duration behavior do not seed the corrected panel.
- Add `scripts/recover_pending_review.py` to save a complete current capture as
  local JSON and CSV without writing upstream tasks or shared database records.

The primary task API had started returning valid durations by the fresh recovery
capture. Therefore the fresh capture itself used those positive source values.
The fallback was additionally tested against the **actual 229 zero-duration rows
saved earlier**: all IDs, owners, and current Auditor stages matched, and the
alternate ranges recovered exactly **17,635 seconds / 04:53:55**.

## Verification

- 118 targeted tests passed, plus five subtests. Coverage includes pagination,
  identity/stage changes, invalid timing, omitted IDs, source failures, pending
  totals, chart captures, viewer restrictions, and callback dependencies.
- Live source verification recovered all 229 earlier zero-duration records.
- Actual localhost refresh/capture/render callbacks produced the successful
  pending chart with 256 Auditor tasks and 24,871 seconds, including Aditya's
  3,617 seconds. No cross-callback dependency cycle was found.
- Two verified instances of this local dashboard were listening on port 8050.
  They were restarted as one updated instance. Browser tabs should be reloaded
  to discard their previous chart stores.

## Retained artifacts

Under `data/reports/pending-review-recovery-2026-11-02/`:

- `recovered-review-tasks.json` and `.csv`: fresh current capture, including
  per-task source provenance. The source remained active; this earlier capture
  had 35 Leader tasks before the later chart check had 36.
- `recovered-zero-duration-tasks.json` and `.csv`: all 229 earlier zero-duration
  records with verified alternate time ranges.
- `dashboard-verification.json`: successful live panel packet and chart response.
- `server.stdout.log` and `server.stderr.log`: restarted local server logs.

Repeat a local evidence capture with:

```powershell
.venv/Scripts/python.exe scripts/recover_pending_review.py
```

Viewer mode deliberately rejects source recovery; collection belongs on the
local dashboard or collector. The existing scheduled snapshot publication path
will include corrected pending panels when it next runs. This local operation
did not deploy code or reconstruct the 52 inaccessible original Friday batches;
their historical cause and membership still require upstream administrative
evidence. Original audit artifacts remain retained separately.

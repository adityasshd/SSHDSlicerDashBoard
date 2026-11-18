"""User-by-return-tier heatmap of evidence-backed BATCH COUNTS.

No cell uses original whole-batch duration as a proxy for time spent
reworking or completing videos. Unknown is a separate count bucket.
"""
from html import escape

import pandas as pd
from slicing_dashboard.plots.theme import format_seconds
from slicing_dashboard.plots.completed_hours_heatmap import completion_total

from slicing_dashboard.plots.guardrails import checked_frame, safe_chart, state_figure
from slicing_dashboard.plots.intensity_chart import intensity_chart
from slicing_dashboard.reporting.rework_tiers import (
    DISPLAY_TIERS,
    LEGACY_UPPER,
    prepare_rework_stacks,
)

VALID_COMPLETION_STATES = ("All", "Completed", "Pending approvals")


def _format_ids(ids) -> str:
    return ", ".join(escape(str(item)) for item in sorted(ids, key=str)) or "Unavailable"


def _count_stacks(frame):
    """Remove durations before calculating tiers; count evidence stands alone."""
    count_frame = frame.drop(columns=['Total Duration (hrs)',
                                      'Avg Batch Duration (hrs)',
                                      'Tier Duration (hrs)'], errors='ignore')
    return prepare_rework_stacks(count_frame.sort_values(
        ['User', 'Completion State'] if 'Completion State' in count_frame else ['User']))


@safe_chart
def build_rework_ratio_chart(
    ratio_df: pd.DataFrame,
    start_date: str,
    is_dark: bool,
    effective_users: list | None = None,
    is_filtering: bool = False,
    show_counts: bool = False,
    completion_state: str = "All",
    completed_evidence=None,
    selected_users=None,
):
    """Show tier batch counts, alongside independent verified completed hours.

    Completed hours are not attributed to any return tier without task-level
    task→batch evidence. All five tier columns stay in BATCH units.
    """
    if completion_state not in VALID_COMPLETION_STATES:
        raise ValueError(f"Invalid completion state: {completion_state!r}")

    frame = checked_frame(
        ratio_df, ["User", "Total Batches"],
        ["Total Batches", *DISPLAY_TIERS, *LEGACY_UPPER,
         "3+ Return Count", "5+ Return Count", "Reworked Once", "Reworked Twice+"],
    )
    if frame.empty:
        return state_figure("No batch data available.", is_dark)
    if is_filtering and effective_users is not None:
        frame = frame[frame["User"].isin(effective_users)]
    frame = frame[frame["Total Batches"] > 0]
    if frame.empty:
        return state_figure("No batch data available.", is_dark)

    has_status = "Completion State" in frame.columns
    if has_status and not frame["Completion State"].isin(
            ("Completed", "Pending approvals")).all():
        raise ValueError("Unknown batch completion state")
    if completion_state != "All":
        if not has_status:
            return state_figure("Batch status unavailable.", is_dark)
        frame = frame[frame["Completion State"] == completion_state].copy()
        if frame.empty:
            return state_figure(f"No {completion_state.lower()} batches available.", is_dark)

    grouping = ["User", "Completion State"] if has_status else ["User"]
    if frame.duplicated(grouping).any():
        raise ValueError("Duplicate user batch totals")

    stacks = _count_stacks(frame)
    users = list(frame.groupby("User")["Total Batches"].sum().sort_values(
        ascending=False, kind="stable").index)

    # The source-date task-efficiency capture is the same evidence powering
    # Completed Hours. It can include completed tasks from batches not in the
    # *current-status* batch cohort. Keep those users rather than silently
    # truncating the completed-hours total to the cohort's roster.
    add_completed_column = completion_state == 'Completed' and completed_evidence is not None
    completed_by_user = {}
    completed_seconds = None
    if add_completed_column:
        completed_seconds = completion_total(completed_evidence, selected_users)
        if completed_seconds is not None:
            for row in completed_evidence['rows']:
                user = row['User']
                if selected_users is not None and user not in selected_users:
                    continue
                completed_by_user[user] = (float(row['seconds']), row.get('tasks'))
            users = sorted(
                set(users) | set(completed_by_user),
                key=lambda user: (-completed_by_user.get(user, (0, None))[0],
                                  -sum(stack['total'] for (name, _), stack in stacks.items() if name == user),
                                  str(user).casefold()))
    categories = [*DISPLAY_TIERS, 'Completed<br>hours'] if add_completed_column else list(DISPLAY_TIERS)

    total_label = '<b>Total</b>'
    counts_matrix, labels, custom_matrix = [], [], []
    for user in [*users, total_label]:
        user_stacks = [
            (state, stack) for (name, state), stack in stacks.items()
            if name == user or user == total_label
        ]
        total = sum(int(stack['total']) for _, stack in user_stacks)
        row_counts, row_custom = [], []
        for index, tier in enumerate(DISPLAY_TIERS):
            count = sum(int(stack['counts'][index]) for _, stack in user_stacks)
            ids = set().union(*(stack['ids'][index] for _, stack in user_stacks))
            by_state = []
            if has_status:
                states = (("Completed", "Pending approvals") if completion_state == "All"
                          else (completion_state,))
                for state in states:
                    state_count = sum(int(stack['counts'][index])
                                      for item_state, stack in user_stacks
                                      if item_state == state)
                    by_state.append(f"{escape(state)}: {state_count} batches")
            row_counts.append(count)
            row_custom.append([
                count, total, (count / total * 100) if total else 0,
                _format_ids(ids), escape('Total' if user == total_label else str(user)),
                escape(tier), "<br>".join(by_state),
            ])
        row_labels = [str(number) for number in row_counts]
        if add_completed_column:
            if user == total_label:
                seconds = completed_seconds
                tasks = (sum(row.get('tasks') for row in completed_evidence.get('rows', [])
                             if (selected_users is None or row['User'] in selected_users))
                         if completed_seconds is not None and
                            all(isinstance(row.get('tasks'), (int, float)) and
                                not isinstance(row.get('tasks'), bool) and row['tasks'] >= 0 and
                                int(row['tasks']) == row['tasks']
                                for row in completed_evidence.get('rows', [])
                                if selected_users is None or row['User'] in selected_users)
                         else None)
            else:
                seconds, tasks = completed_by_user.get(user, (None, None))
            hours = seconds / 3600 if seconds is not None else None
            row_counts.append(hours)
            row_labels.append(format_seconds(seconds, compact=True) if seconds is not None else '—')
            row_custom.append([
                None, None, None, 'Unavailable',
                escape('Total' if user == total_label else str(user)),
                'Completed video hours',
                (f"{format_seconds(seconds)} · "
                 f"{int(tasks) if tasks is not None else 'Unknown'} completed tasks"
                 if seconds is not None else 'Verified completed hours unavailable'),
            ])
            # The other columns are batch counts, not a distribution of these
            # hours. The completed-hours column retains the entire value.
            for cell in row_custom[:-1]:
                cell[6] = (f"{cell[0]} / {cell[1]} batches ({cell[2]:.1f}%)"
                           + (f"<br>{cell[6]}" if cell[6] else '')
                           + f"<br>IDs: {cell[3]}")
        counts_matrix.append(row_counts)
        labels.append(row_labels)
        custom_matrix.append(row_custom)

    # Column-wise normalization permits independent batch-count and hour
    # columns in ONE aligned matrix. Never sum these unlike units together.
    figure = intensity_chart(
        [*users, total_label], categories,
        {"Values": (counts_matrix, labels)},
        custom_matrix,
        (("<b>%{customdata[4]}</b><br>%{customdata[5]}"
          "<br>%{customdata[6]}<extra></extra>")
         if add_completed_column else
         ("<b>%{customdata[4]}</b><br>%{customdata[5]}"
          "<br>%{customdata[0]} / %{customdata[1]} batches (%{customdata[2]:.1f}%)"
          "<br>%{customdata[6]}"
          "<br>IDs: %{customdata[3]}<extra></extra>")),
        ("Rework tiers · batches and completed hours" if add_completed_column
         else "Rework intensity by tier"),
        is_dark, subtitle='', show_counts=False, value_key="Values",
    )
    meta = dict(figure.layout.meta)
    meta.update({
        'value_unit': 'mixed' if add_completed_column else 'Batches',
        'column_units': ['batches'] * len(DISPLAY_TIERS) +
                        (['hours'] if add_completed_column else []),
        'tier_batch_totals': [int(v) for v in counts_matrix[-1][:len(DISPLAY_TIERS)]],
        'verified_completed_seconds': completed_seconds if add_completed_column else None,
        'completed_hour_column_index': len(DISPLAY_TIERS) if add_completed_column else None,
        'return_tier_completed_hours_attributed': False,
        'metric': ('completed_seconds_and_cohort_batch_counts' if add_completed_column
                   else 'return_tier_batch_counts'),
    })
    figure.update_layout(meta=meta)
    return figure

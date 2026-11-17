"""User-by-tier rework heatmap, filterable by completion state.

Each batch's original duration is counted once in its return tier.
The input report must already be scoped to the desired reporting period.
"""

from html import escape
from math import isfinite

import pandas as pd

from slicing_dashboard.plots.guardrails import checked_frame, safe_chart, state_figure
from slicing_dashboard.plots.intensity_chart import intensity_chart
from slicing_dashboard.plots.theme import format_seconds
from slicing_dashboard.reporting.rework_tiers import (
    LEGACY_UPPER,
    TIERS,
    prepare_rework_stacks,
)

VALID_COMPLETION_STATES = ("All", "Completed", "Pending approvals")


def _format_ids(ids) -> str:
    """Escape raw batch IDs for a Plotly HTML hover label."""
    return (
        ", ".join(escape(str(item)) for item in sorted(ids, key=str)) or "Unavailable"
    )


@safe_chart
def build_rework_ratio_chart(
    ratio_df: pd.DataFrame,
    start_date: str,
    is_dark: bool,
    effective_users: list | None = None,
    is_filtering: bool = False,
    show_counts: bool = False,
    completion_state: str = "All",
):
    """Build a user × return-tier heatmap of actual batch hours or batch counts.

    completion_state:
      * All: combine the two states, retaining their hover breakdown.
      * Completed: show only completed batches.
      * Pending approvals: show only pending-approval batches.

    `start_date` is retained for compatibility; filtering dates happens upstream.
    """
    if completion_state not in VALID_COMPLETION_STATES:
        raise ValueError(f"Invalid completion state: {completion_state!r}")

    frame = checked_frame(
        ratio_df,
        ["User", "Total Batches"],
        [
            "Total Batches",
            *TIERS,
            *LEGACY_UPPER,
            "3+ Return Count",
            "5+ Return Count",
            "Reworked Once",
            "Reworked Twice+",
            "Total Duration (hrs)",
            "Avg Batch Duration (hrs)",
        ],
    )
    if frame.empty:
        return state_figure("No submitted batch data available.", is_dark)

    if is_filtering and effective_users is not None:
        frame = frame[frame["User"].isin(effective_users)]
    frame = frame[frame["Total Batches"] > 0]
    if frame.empty:
        return state_figure("No submitted batch data available.", is_dark)

    has_status = "Completion State" in frame.columns
    if (
        has_status
        and not frame["Completion State"].isin(("Completed", "Pending approvals")).all()
    ):
        raise ValueError("Unknown batch completion state")

    if completion_state != "All":
        if not has_status:
            return state_figure(
                "Completion status unavailable for this dataset.", is_dark
            )
        frame = frame[frame["Completion State"] == completion_state].copy()
        if frame.empty:
            return state_figure(
                f"No {completion_state.lower()} batches available.", is_dark
            )

    grouping = ["User", "Completion State"] if has_status else ["User"]
    if frame.duplicated(grouping).any():
        raise ValueError("Duplicate user batch totals")

    stacks = prepare_rework_stacks(frame.sort_values(grouping))
    users = list(
        frame.groupby("User")["Total Batches"]
        .sum()
        .sort_values(ascending=False, kind="stable")
        .index
    )

    total_label = '<b>Total</b>'
    hours_matrix, counts_matrix, hour_labels, custom_matrix = [], [], [], []
    users.append(total_label)
    for user in users:
        user_stacks = [
            (state, stack) for (name, state), stack in stacks.items() if name == user or user == total_label
        ]
        total = int(sum(stack["total"] for _, stack in user_stacks))
        row_hours, row_counts, row_labels, row_custom = [], [], [], []

        for index, tier in enumerate(TIERS):
            count = int(sum(stack["counts"][index] for _, stack in user_stacks))
            durations = [stack["hours"][index] for _, stack in user_stacks]
            duration = (
                sum(float(value) for value in durations)
                if all(value is not None for value in durations)
                else None
            )
            if duration is not None and (not isfinite(duration) or duration < 0):
                raise ValueError("Invalid tier duration")

            weight = sum(stack["weights"][index] for _, stack in user_stacks)
            ids = set().union(*(stack["ids"][index] for _, stack in user_stacks))
            formatted_duration = (
                format_seconds(duration * 3600)
                if duration is not None
                else "Unavailable"
            )

            details = []
            if has_status:
                # For a selected state show only that state; for All show both.
                detail_states = (
                    ("Completed", "Pending approvals")
                    if completion_state == "All"
                    else (completion_state,)
                )
                for state in detail_states:
                    state_stacks = [stack for item_state, stack in user_stacks if item_state == state]
                    known_hours = [stack['hours'][index] for stack in state_stacks]
                    state_hours = sum(known_hours) if all(value is not None for value in known_hours) else None
                    state_count = int(sum(stack['counts'][index] for stack in state_stacks))
                    state_duration = (
                        format_seconds(float(state_hours) * 3600)
                        if state_hours is not None
                        else "Unavailable"
                    )
                    details.append(
                        f"{escape(state)}: {state_duration} · {state_count} "
                        f"{'batch' if state_count == 1 else 'batches'}"
                    )
            else:
                details.append("Completion status unavailable")

            row_hours.append(duration)
            row_counts.append(count)
            row_labels.append(
                format_seconds(duration * 3600, compact=True)
                if duration is not None
                else "—"
            )
            row_custom.append(
                [
                    count,
                    total,
                    count / total * 100 if total else 0,
                    weight,
                    duration,
                    duration / count if duration is not None and count else None,
                    formatted_duration,
                    _format_ids(ids),
                    escape('Total' if user == total_label else str(user)),
                    escape(str(tier)),
                    "<br>".join(details),
                ]
            )

        hours_matrix.append(row_hours)
        counts_matrix.append(row_counts)
        hour_labels.append(row_labels)
        custom_matrix.append(row_custom)

    note = "Each batch duration counted once"
    if completion_state != "All":
        note += f" · {completion_state} only"
    elif has_status:
        note += " · Completed + Pending approvals"
    else:
        note += " · completion status unavailable"
    note += ('<br>Batch / return-date cohort · whole batches, not task completion hours'
             '<br>Latest saved status · return tiers use observed events through selected end')

    return intensity_chart(
        users,
        list(TIERS),
        {
            "Hours": (hours_matrix, hour_labels),
            "Batches": (
                counts_matrix,
                [[str(value) for value in row] for row in counts_matrix],
            ),
        },
        custom_matrix,
        (
            "<b>%{customdata[8]}</b><br>%{customdata[9]}"
            "<br>Duration: %{customdata[6]}"
            "<br>%{customdata[0]} of %{customdata[1]} batches "
            "(%{customdata[2]:.1f}%)"
            "<br>%{customdata[10]}"
            "<br>IDs: %{customdata[7]}<extra></extra>"
        ),
        "Rework intensity by tier",
        is_dark,
        note,
        show_counts=show_counts,
    )

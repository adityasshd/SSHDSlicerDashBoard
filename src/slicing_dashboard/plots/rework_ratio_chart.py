"""User-by-return-tier heatmap of evidence-backed BATCH COUNTS.

No cell uses original whole-batch duration as a proxy for time spent
reworking or completing videos. Unknown is a separate count bucket.
"""
from html import escape

import pandas as pd

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
):
    """Render one batch-count per user/tier, never original batch video hours."""
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
        counts_matrix.append(row_counts)
        labels.append([str(number) for number in row_counts])
        custom_matrix.append(row_custom)

    # The helper uses the numeric matrix as the color coordinate and appends
    # the unnormalized value in the final customdata cell. No video seconds.
    return intensity_chart(
        [*users, total_label],
        list(DISPLAY_TIERS),
        {"Batches": (counts_matrix, labels)},
        custom_matrix,
        ("<b>%{customdata[4]}</b><br>%{customdata[5]}"
         "<br>%{customdata[0]} / %{customdata[1]} batches (%{customdata[2]:.1f}%)"
         "<br>%{customdata[6]}"
         "<br>IDs: %{customdata[3]}<extra></extra>"),
        "Rework intensity by tier",
        is_dark,
        subtitle='', show_counts=False, value_key="Batches",
    )

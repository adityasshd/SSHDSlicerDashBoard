"""Checks for source totals, duration shares, and summary API compatibility."""
from unittest.mock import MagicMock

import pytest

from slicing_dashboard.plots.kpi_overview import build_kpi_layout
from slicing_dashboard.reporting.dashboard_panels import selected_summary
from slicing_dashboard.reporting.kpi_overview import ordered_kpis
from tests.test_assignable_pool import manager
from tests.test_daily_report_page import components, payload_text


FUNNEL = {'assigned': {'duration_seconds': 5400}, 'rework': {'duration_seconds': 1800}}
SUMMARY = {'total_approved_duration': 36000, 'total_pending_duration': 7200,
           'leader_review_duration': 3600, 'auditor_review_duration': 1800,
           'admin_review_duration': 1800, 'assignable_duration': 900, 'assignable_count': 3}


@pytest.mark.parametrize('dark', [True, False])
def test_primary_totals_and_duration_shares_use_independent_sources(dark):
    layout = build_kpi_layout(SUMMARY, FUNNEL, dark)
    text = payload_text(layout)
    assert 'Completed tasks' not in text
    assert '10:00:00' in text and '02:00:00' in text
    bars = [node for node in components(layout) if getattr(node, 'role', None) == 'progressbar']
    assert [bar.to_plotly_json()['props']['aria-valuenow'] for bar in bars] == [75, 25, 50, 25, 25]
    # These shares describe duration within each workload, never task completion.
    assert all('duration' in bar.to_plotly_json()['props']['aria-valuetext'] for bar in bars)


def test_review_total_is_not_replaced_when_stage_durations_differ():
    layout = build_kpi_layout({**SUMMARY, 'total_pending_duration': 10800}, FUNNEL, True)
    text = payload_text(layout)
    assert '03:00:00' in text
    assert 'Review stage durations differ' in text


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), -1, 'bad'])
def test_invalid_assignment_stage_cannot_create_a_false_total_or_partial_bar(value):
    funnel = {**FUNNEL, 'rework': {'duration_seconds': value}}
    assert ordered_kpis(SUMMARY, funnel)['assigned_now_duration'] is None
    layout = build_kpi_layout(SUMMARY, funnel, True)
    assert 'Breakdown unavailable' in payload_text(layout)
    bars = [node for node in components(layout) if getattr(node, 'role', None) == 'progressbar']
    assert len(bars) == 3  # Only the complete review breakdown has percentages.


def test_zero_workload_and_missing_workload_are_distinct():
    zero = {stage: {'duration_seconds': 0} for stage in FUNNEL}
    assert ordered_kpis(SUMMARY, zero)['assigned_now_duration'] == 0
    assert ordered_kpis(SUMMARY, {})['assigned_now_duration'] is None
    assert 'No duration in stages' in payload_text(build_kpi_layout(SUMMARY, zero, True))


@pytest.mark.parametrize('selected,fallback', [(None, False), (['Riya'], False), (None, True)])
def test_summary_api_keeps_values_and_call_counts_without_completed_task_fields(selected, fallback):
    dm = manager()
    current = {'completed_duration_seconds': 36000, 'leader_review_duration_seconds': 3600,
               'auditor_review_duration_seconds': 1800, 'admin_review_duration_seconds': 1800,
               'rework_duration_seconds': 600, 'error_review_duration_seconds': 300}
    dm._get_canonical_name = MagicMock(return_value='Riya')
    dm.fetch_annotator_efficiency.side_effect = (
        RuntimeError('Unavailable') if fallback else
        [(current, [{**current, 'username': 'Riya'}]), ({'completed_duration_seconds': 18000}, [])]
    )
    dm.fetch_dashboard_data.return_value = {
        'metrics': {'slice_completed_duration_seconds': 36000, 'review_pending_duration_seconds': 7200},
        'breakdowns': {'slice_funnel': [{'key': stage, **row} for stage, row in FUNNEL.items()]},
    }
    kpis = dm.get_summary_kpis('2026-11-01', '2026-11-10', selected_users=selected)
    if fallback:
        assert kpis.get('_source_error') == 'RuntimeError'
        return
    assert kpis['total_approved_duration'] == 36000
    assert kpis['assigned_now_duration'] == 7200
    assert kpis['total_pending_duration'] == 7200
    assert not {'completed_tasks', 'prev_completed_tasks', 'completed_pct', 'total_tasks'} & kpis.keys()
    keys = list(kpis)
    assert keys.index('total_approved_duration') < keys.index('assigned_now_duration') < keys.index('total_pending_duration') < keys.index('assignable_duration')
    assert dm.fetch_dashboard_data.call_count == 1
    assert dm.scraper._client.get.call_count == 1


def test_user_filter_updates_period_totals_and_keeps_current_assignment_scope():
    all_kpis = ordered_kpis(SUMMARY, FUNNEL)
    filtered = selected_summary({'all': all_kpis, 'users': {
        'Riya': {'total_approved_duration': 7200, 'total_pending_duration': 900},
    }}, ['Riya'], ['Riya', 'Priya'])
    assert filtered['total_approved_duration'] == 7200
    assert filtered['total_pending_duration'] == 900
    assert filtered['assigned_now_duration'] == 7200
    assert filtered['assignable_duration'] == 900
    # Already mapped summaries and older captures both remain renderable.
    assert ordered_kpis(filtered, {}) == filtered


@pytest.mark.parametrize('previous', [({'_source_error': 'MissingPeriod'}, []), ConnectionError('Unavailable')])
def test_missing_previous_period_keeps_current_values_and_unknown_comparison(previous):
    dm = manager()
    dm._get_reporting_name = lambda uid, username: username
    dm.fetch_annotator_efficiency.side_effect = [({}, [
        {'username': 'Riya', 'completed_duration_seconds': 7200, 'rework_duration_seconds': 900},
        {'username': 'Admin', 'completed_duration_seconds': 99999},
    ]), previous]
    values = dm.get_summary_kpis('2026-11-01', '2026-11-17')
    assert values['total_approved_duration'] == 7200
    assert values['rework_duration'] == 900
    assert values['prev_approved_duration'] is None and values['approved_pct'] is None
    selected = selected_summary({'all': values, 'users': {'Riya': values}}, ['Riya'], ['Riya'])
    assert selected['total_approved_duration'] == 7200 and selected['approved_pct'] is None

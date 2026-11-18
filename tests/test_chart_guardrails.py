import math
from unittest.mock import MagicMock

import pandas as pd
import pytest

from slicing_dashboard.plots.individual_chart import build_individual_chart
from slicing_dashboard.plots.pending_chart import build_pending_chart
from slicing_dashboard.plots.assigned_chart import build_assigned_chart
from slicing_dashboard.plots.rework_ratio_chart import build_rework_ratio_chart
from slicing_dashboard.plots.work_trend_chart import build_user_comparison_chart
from slicing_dashboard.plots.report_insights import build_activity_calendar
from slicing_dashboard.plots.theme import format_seconds
from slicing_dashboard.processing.batch_ratios import batch_ratios


def _heatmap_matrix(figure, attribute='z'):
    """Recover original (un-normalized) user values from aligned heatmap cells."""
    if not figure.data:
        return []
    trace = figure.data[0]
    n = len(trace.y) - int(trace.y[-1] == '<b>Total</b>')
    if attribute == 'customdata':
        return [[list(cell[:-1]) for cell in row] for row in trace.customdata[:n]]
    return [[cell[-1] for cell in row] for row in trace.customdata[:n]]


@pytest.mark.parametrize('frame', [None, pd.DataFrame(), pd.DataFrame({'User': [None]}),
                                  pd.DataFrame({'User': ['A'], 'Duration': [float('inf')], 'Count': [1], 'Stage': ['Pending Leader']})])
def test_malformed_chart_is_isolated_and_empty_axes_are_hidden(frame):
    for builder in (lambda: build_pending_chart(frame, True),
                    lambda: build_individual_chart(frame, '', '', True),
                    lambda: build_assigned_chart(frame, True),
                    lambda: build_rework_ratio_chart(frame, '', True)):
        figure = builder()
        assert not figure.data and figure.layout.annotations
        assert figure.layout.xaxis.visible is False
        figure.to_json()


@pytest.mark.parametrize('seconds', [0, .000001, 1e24])
def test_scales_keep_finite_extreme_values_and_full_names(seconds):
    names = ['Very long full username ' + str(i) * 35 for i in range(50)]
    frame = pd.DataFrame({'User': names, 'Completed Duration': [seconds] * 50})
    figure = build_individual_chart(frame, '2026-10-01', '2026-10-07', True)
    assert sum(len(trace.x) for trace in figure.data) == 50
    assert sum(sum(trace.y) for trace in figure.data) == pytest.approx(seconds / 3600 * 50)
    assert all(math.isfinite(value) for value in figure.layout.yaxis.range)
    assert all(len(label) <= 16 for label in figure.layout.xaxis.ticktext)
    assert set(value for trace in figure.data for value in trace.x) == set(names)


def test_missing_durations_are_not_formatted_as_zero():
    assert format_seconds(0) == '00:00:00'
    for value in (None, float('nan'), float('inf'), 'invalid'):
        assert format_seconds(value) == 'Unavailable'
    assert format_seconds(.001) == '00:00:00'


def test_duplicate_daily_records_cannot_overwrite_another_value():
    rows = [{'date': '2026-10-01', 'user': 'A', 'total_seconds': value} for value in [1, 9]]
    figure = build_user_comparison_chart(rows)
    assert not figure.data and 'unavailable' in figure.layout.annotations[0].text
    calendar, count = build_activity_calendar({}, 'A', 'invalid')
    assert count == 0 and not calendar.data


def test_batch_distribution_counts_entities_and_unique_returns_only():
    batches = [dict(batch_id='one', batch_date='2026-10-01', status='batch_completed', return_count=1, total_duration_seconds=720000),
               dict(batch_id='two', batch_date='2026-10-01', status='batch_member_assigned', total_duration_seconds=100)]
    event = dict(event_id='return-one', batch_id='one', returned_at='2026-10-01T03:00:00Z')
    frame = batch_ratios(batches, [event, event], '2026-10-01', '2026-10-07', lambda batch: 'A')
    assert frame.iloc[0]['Total Batches'] == 1
    assert frame.iloc[0]['1 Rework'] == 1
    assert frame.iloc[0]['Total Duration (hrs)'] == 200


@pytest.mark.parametrize('dark', [True, False])
def test_rework_matrix_preserves_counts_and_never_shows_original_hours(dark):
    frame = pd.DataFrame([{'User': 'A', 'Total Batches': 6, 'No Rework': 1,
                           '1 Rework': 1, '2 Reworks': 1, '3 Reworks': 1,
                           '4 Reworks': 1, '5+ Reworks': 1,
                           'Total Duration (hrs)': 10000}])
    original = frame.copy(deep=True)
    figure = build_rework_ratio_chart(frame, '2026-10-01', dark)
    trace = figure.data[0]
    assert trace.type == 'heatmap'
    assert _heatmap_matrix(figure)[0] == [1, 1, 1, 3, 0]
    for cell, count in zip(_heatmap_matrix(figure, 'customdata')[0],
                           [1, 1, 1, 3, 0]):
        assert cell[:3] == pytest.approx([count, 6, count * 100 / 6])
    assert 'Duration' not in trace.hovertemplate
    assert '10000' not in figure.to_json()
    assert figure.data[0].x[-1] == 'Unknown'
    assert figure.layout.hovermode == 'closest'
    assert figure.layout.title.subtitle.text is None
    with_counts = build_rework_ratio_chart(frame, '2026-10-01', dark, show_counts=True)
    assert [item.text for item in with_counts.layout.annotations][:5] == [
        '1', '1', '1', '3', '0']
    pd.testing.assert_frame_equal(frame, original)


def test_grouped_reworks_use_exact_unique_return_counts_above_three():
    batches = [dict(batch_id=batch, batch_date='2026-10-01', status='batch_completed', return_count={'clean': 0, 'five': 5, 'seven': 8}[batch], total_duration_seconds=0)
               for batch in ['clean', 'five', 'seven']]
    events = [dict(event_id=f'{batch}-{index}', batch_id=batch, returned_at='2026-10-02T03:00:00Z')
              for batch, count in [('five', 5), ('seven', 7)] for index in range(count)]
    # Duplicate observations and returns beyond the selected end date add no weight.
    frame = batch_ratios(batches, [*events, events[0], dict(event_id='later', batch_id='seven',
                        returned_at='2026-10-08T03:00:00Z')],
                        '2026-10-01', '2026-10-07', lambda batch: 'A')
    assert frame.iloc[0]['3+ Reworks'] == 2
    assert frame.iloc[0]['3+ Return Count'] == 12
    figure = build_rework_ratio_chart(frame, '2026-10-01', True)
    assert _heatmap_matrix(figure)[0] == [1, 0, 0, 2, 0]
    assert list(_heatmap_matrix(figure, 'customdata')[0][-2][:3]) == pytest.approx([2, 3, 200 / 3])


def test_rework_tooltip_ids_are_scoped_to_the_hovered_tier():
    batches = [dict(batch_id=batch, username=account, batch_date='2026-10-01',
                    status='batch_completed', total_duration_seconds=3600,
                    return_count={'clean': 0, 'one': 1, 'another': 1, 'two': 2}[batch])
               for batch, account in [('clean', 'A-clean'), ('one', 'A-return'),
                                      ('another', 'A-return'), ('two', 'B-return')]]
    events = [dict(event_id=f'{batch}-{index}', batch_id=batch, returned_at='2026-10-02T03:00:00Z')
              for batch, count in [('one', 1), ('another', 1), ('two', 2)] for index in range(count)]
    frame = batch_ratios(batches, events, '2026-10-01', '2026-10-07', lambda batch: 'Person')
    figure = build_rework_ratio_chart(frame, '2026-10-01', True)
    cells = _heatmap_matrix(figure, 'customdata')[0]
    assert [cell[3] for cell in cells[:3]] == ['A-clean', 'A-return', 'B-return']
    assert [cell[0] for cell in cells] == [1, 2, 1, 0, 0]
    assert 'IDs: %{customdata[3]}' in figure.data[0].hovertemplate


def test_weighted_rework_keeps_clean_users_and_legacy_tiers_with_filtering():
    frame = pd.DataFrame([{'User': 'Clean', 'Total Batches': 4, 'No Rework': 4,
                           'Reworked Once': 0, 'Reworked Twice+': 0},
                          {'User': 'Returned', 'Total Batches': 2, 'No Rework': 1,
                           'Reworked Once': 0, 'Reworked Twice+': 1},
                          {'User': 'Empty', 'Total Batches': 0, 'No Rework': 0,
                           'Reworked Once': 0, 'Reworked Twice+': 0}])
    figure = build_rework_ratio_chart(frame, '', True)
    assert list(figure.data[0].y[:-1]) == ['Clean', 'Returned']
    assert _heatmap_matrix(figure)[0] == [4, 0, 0, 0, 0]
    filtered = build_rework_ratio_chart(frame, '', True, ['Returned'], True)
    assert list(filtered.data[0].y[:-1]) == ['Returned']
    assert _heatmap_matrix(filtered)[0] == [1, 0, 1, 0, 0]


def test_three_plus_durations_and_accounts_survive_saved_panel_roundtrip():
    from slicing_dashboard.reporting.dashboard_panels import frame_payload, panel_frame
    batches = [dict(batch_id=str(index), username=f'account-{index}', batch_date='2026-10-01',
                    status='batch_completed' if index % 2 else 'batch_pending_admin_review',
                    total_duration_seconds=hours * 3600, return_count=[0, 1, 2, 3, 4, 7][index])
               for index, hours in enumerate([1, 2, 3, 4, 5, 6])]
    events = [dict(event_id=f'{index}-{attempt}', batch_id=str(index), returned_at='2026-10-02T03:00:00Z')
              for index, count in enumerate([0, 1, 2, 3, 4, 7]) for attempt in range(count)]
    frame = batch_ratios(batches, events + [events[-1]], '2026-10-01', '2026-10-07', lambda b: 'Person')
    restored = panel_frame({'data': frame_payload(frame, 'rework')})
    figure = build_rework_ratio_chart(restored, '', True)
    trace = figure.data[0]
    assert list(figure.data[0].x) == ['No Rework', '1 Rework', '2 Reworks', '3+ Reworks', 'Unknown']
    assert _heatmap_matrix(figure)[0] == [1, 1, 1, 3, 0]
    assert [cell[0] for cell in _heatmap_matrix(figure, 'customdata')[0]] == [1, 1, 1, 3, 0]
    cell = _heatmap_matrix(figure, 'customdata')[0][-2]
    assert cell[0] == 3 and cell[3] == 'account-3, account-4, account-5'
    assert 'Completed: 2 batches' in cell[6]
    assert 'Pending approvals: 1 batches' in cell[6]
    assert sum(_heatmap_matrix(figure)[0]) == 6
    assert figure.layout.meta['value_unit'] == 'Batches'


def test_legacy_three_plus_merges_scoped_durations_without_using_person_total():
    frame = pd.DataFrame([{'User': 'A', 'Total Batches': 4, 'No Rework': 1,
        '3 Reworks': 1, '4 Reworks': 1, '5+ Reworks': 1, '5+ Return Count': 8,
        'Total Duration (hrs)': 20, 'Tier Duration (hrs)': {
            'No Rework': 2, '3 Reworks': 4, '4 Reworks': 6, '5+ Reworks': 8},
        'Tier IDs': {'No Rework': 'clean', '3 Reworks': 'three', '4 Reworks': 'four', '5+ Reworks': 'eight'}}])
    figure = build_rework_ratio_chart(frame, '', False)
    cells = _heatmap_matrix(figure, 'customdata')[0]
    assert [cell[0] for cell in cells] == [1, 0, 0, 3, 0]
    assert cells[-2][3] == 'eight, four, three'
    assert '20' not in figure.to_json() or 'Total Duration' not in figure.to_json()


def test_ratio_does_not_generate_batches_from_efficiency_or_current_rework():
    from slicing_dashboard.data_manager import DataManager
    dm = DataManager.__new__(DataManager)
    dm._batches_master_cache = {}
    dm.sync_batches_master = MagicMock()
    dm.sync_batch_returns = MagicMock(return_value=[])
    dm.fetch_annotator_efficiency = MagicMock(return_value=({}, [{'completed_duration_seconds': 500000}]))
    dm.get_live_rework_by_user = MagicMock(return_value={'A': {'count': 500}})
    assert dm.get_batch_rework_ratio_df('2026-10-01', '2026-10-07').empty
    dm.fetch_annotator_efficiency.assert_not_called()
    dm.get_live_rework_by_user.assert_not_called()


@pytest.mark.parametrize('dark', [True, False])
def test_visible_stack_totals_are_outside_and_axis_has_ten_percent_headroom(dark):
    frame = pd.DataFrame({'User': ['A', 'A', 'B'], 'Stage': ['Pending Leader', 'Pending Admin', 'Pending Leader'],
                          'Duration': [3600, 7200, 1800], 'Count': [1, 2, 1]})
    pending = build_pending_chart(frame, dark)
    assert _heatmap_matrix(pending) == [[1, 0, 2], [.5, 0, 0]]
    assert pending.layout.meta['column_maxima'] == [1, 0, 2]
    assert pending.layout.yaxis.autorange == 'reversed'
    assigned = build_assigned_chart(frame.assign(Stage=['New Assigned', 'Rework Assigned', 'New Assigned']), dark)
    labels = {item.y: item for item in assigned.layout.annotations if item.name == 'bar-hour-total'}
    assert labels['A'].text == '03:00' and labels['A'].x == 3
    assert all(item.xanchor == 'left' and item.xshift > 0 for item in labels.values())
    assert list(assigned.layout.xaxis.range) == pytest.approx([0, 3.3])
    assert sum(sum(trace.x) for trace in assigned.data if trace.type == 'bar') == 3.5


def test_daily_bar_total_excludes_old_rework_but_keeps_its_marker_in_range():
    from slicing_dashboard.plots.error_rework_chart import build_error_rework_chart
    frame = pd.DataFrame({'User': ['A'], 'New Work Duration': [3600], 'Same-day Rework Duration': [1800],
                          'Old Rework Duration': [18000], 'Total Work Duration': [5400]})
    figure = build_error_rework_chart(frame, 'Yesterday', True)
    label = next(item for item in figure.layout.annotations if item.name == 'bar-hour-total')
    assert (label.text, label.y) == ('01:30', 1.5)
    assert list(figure.layout.yaxis.range) == pytest.approx([0, 5.5])
    assert len(figure.data) == 3  # Labels do not add extra series or duplicate table rows.


def test_composition_totals_keep_unknown_gaps_and_verified_zero():
    from slicing_dashboard.plots.work_trend_chart import build_work_composition_chart
    rows = [{'date': '2026-10-07', 'new_seconds': None, 'same_day_rework_seconds': None,
             'old_rework_seconds': None, 'total_seconds': None},
            {'date': '2026-10-08', 'new_seconds': 0, 'same_day_rework_seconds': 0,
             'old_rework_seconds': 0, 'total_seconds': 0}]
    figure = build_work_composition_chart(rows)
    labels = [item for item in figure.layout.annotations if item.name == 'bar-hour-total']
    assert len(labels) == 1 and labels[0].x == '2026-10-08' and labels[0].text == '00:00'
    assert list(figure.layout.yaxis.range) == [0, 1]


@pytest.mark.parametrize('seconds', [.000001, 1e24])
def test_extreme_duration_labels_use_clock_format_and_preserve_numeric_coordinates(seconds):
    frame = pd.DataFrame({'User': ['A'], 'Stage': ['New Assigned'], 'Duration': [seconds]})
    figure = build_assigned_chart(frame, True)
    label = next(item for item in figure.layout.annotations if item.name == 'bar-hour-total')
    assert ':' in label.text and 'h' not in label.text
    assert figure.layout.xaxis.range[1] == pytest.approx(seconds / 3600 * 1.1)


def test_completed_lollipop_labels_and_stems_preserve_values_and_selection():
    figure = build_individual_chart(pd.DataFrame({'User': ['A'], 'Completed Duration': [9000]}), '', '', True)
    assert figure.data[0].text[0] == '02:30'
    assert figure.data[0].type == 'scatter' and figure.data[0].mode == 'markers+text'
    assert figure.data[0].textposition == 'top center' and figure.data[0].cliponaxis is False
    assert figure.layout.clickmode == 'event+select'
    assert figure.layout.shapes[0].y0 == 0 and figure.layout.shapes[0].y1 == 2.5
    assert figure.layout.shapes[0].line.color == figure.data[0].marker.color
    assert list(figure.layout.yaxis.range) == pytest.approx([0, 2.75])


@pytest.mark.parametrize('dark', [True, False])
def test_pending_matrix_combines_hours_and_counts_without_changing_the_scale(dark):
    frame = pd.DataFrame([
        dict(User='A', Stage='Pending Leader', Duration=3600, Count=2, IDs='first'),
        dict(User='A', Stage='Pending Leader', Duration=1800, Count=1, IDs='second, first'),
        dict(User='B', Stage='Pending Admin', Duration=0, Count=4, IDs='third'),
    ])
    frame.attrs['captured_at'] = '2026-11-16T00:00:00Z'
    original = frame.copy(deep=True)
    figure = build_pending_chart(frame, dark)
    trace = figure.data[0]
    assert list(trace.y[:-1]) == ['A', 'B']
    assert _heatmap_matrix(figure) == [[1.5, 0, 0], [0, 0, 0]]
    assert list(trace.customdata[0][0][2:-1]) == ['01:30:00', 3, 'first, second']
    assert trace.customdata[1][2][3] == 4
    assert figure.layout.meta['captured_at'] == frame.attrs['captured_at']
    assert not figure.layout.updatemenus
    combined = build_pending_chart(frame, dark, show_counts=True)
    assert _heatmap_matrix(combined) == _heatmap_matrix(figure)
    assert combined.layout.meta['column_maxima'] == figure.layout.meta['column_maxima']
    assert [item.text for item in combined.layout.annotations] == ['01:30 / 3', '00:00 / 0', '00:00 / 0', '00:00 / 0', '00:00 / 0', '00:00 / 4', '01:30 / 3', '00:00 / 0', '00:00 / 4']
    assert trace.hoverlabel.bgcolor[0][0] != trace.hoverlabel.bgcolor[0][1]
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize('dark', [True, False])
def test_stack_and_lollipop_tooltips_match_their_data_colors(dark):
    frame = pd.DataFrame({'User': ['A'], 'Stage': ['New Assigned'], 'Duration': [3600]})
    assigned = build_assigned_chart(frame, dark)
    for trace in assigned.data:
        if trace.type == 'bar':
            assert trace.hoverlabel.bgcolor == trace.marker.color
    completed = build_individual_chart(pd.DataFrame({'User': ['A'], 'Completed Duration': [3600]}), '', '', dark)
    assert completed.data[0].hoverlabel.bgcolor == completed.data[0].marker.color


def test_assigned_combined_labels_sum_task_counts_and_keep_hour_coordinates():
    frame = pd.DataFrame({'User': ['A', 'A', 'B'], 'Stage': ['New Assigned', 'Rework Assigned', 'New Assigned'],
                          'Duration': [3600, 1800, 0], 'Count': [2, 3, 4]})
    figure = build_assigned_chart(frame, True, show_counts=True)
    totals = {item.y: item for item in figure.layout.annotations if item.name == 'bar-hour-total'}
    assert totals['A'].text == '01:30 / 5' and totals['A'].x == 1.5
    assert totals['B'].text == '00:00 / 4'
    assert sum(sum(trace.x) for trace in figure.data if trace.type == 'bar') == 1.5
    assert figure.layout.meta['bar_count_index'] == 2
    assert all('/' in text for trace in figure.data if trace.type == 'bar' for text in trace.text)
    missing = build_assigned_chart(frame.drop(columns='Count'), True, show_counts=True)
    assert all(item.text.endswith('/ —') for item in missing.layout.annotations if item.name == 'bar-hour-total')

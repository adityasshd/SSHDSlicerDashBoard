"""Independent heatmap column color ranges must never change source values."""
import copy

import pytest

from slicing_dashboard.plots.intensity_chart import intensity_chart


def fixture(hours_b=100, *, with_total=True):
    users = ['A', 'B'] + (['<b>Total</b>'] if with_total else [])
    categories = ['No Rework', '1 Rework', '2 Reworks']
    values = [[1.0, float(hours_b), None],
              [2.0, 10.0, 0.0]]
    counts = [[1, 2, 0], [2, 1, 0]]
    if with_total:
        values.append([3.0, float(hours_b) + 10, None])
        counts.append([3, 3, 0])
    labels = [['01:00', 'large', '—'], ['02:00', 'small', '00:00']]
    if with_total:
        labels.append(['03:00', 'total', '—'])
    custom = [[[f'{u}-{cat}', idx] for idx, cat in enumerate(categories)] for u in users]
    metrics = {'Hours': (values, labels),
               'Batches': (counts, [[str(v) for v in row] for row in counts])}
    return users, categories, metrics, custom


def render(hours_b=100, *, with_total=True, dark=True, counts=False):
    users, categories, metrics, custom = fixture(hours_b, with_total=with_total)
    return intensity_chart(users, categories, metrics, custom,
                           '%{customdata[0]}<extra></extra>', 'Test intensity',
                           dark, 'Test subtitle', show_counts=counts)


@pytest.mark.parametrize('dark', [False, True])
def test_each_category_has_its_own_original_hour_range(dark):
    fig = render(dark=dark)
    assert len(fig.data) == 4  # one trace / column plus neutral totals
    assert [list(trace.x) for trace in fig.data[:3]] == [
        ['No Rework'], ['1 Rework'], ['2 Reworks']]
    assert [trace.zmax for trace in fig.data[:3]] == [2, 100, 1]
    assert [list(trace.z) for trace in fig.data[:3]] == [
        [[1], [2]], [[100], [10]], [[None], [0]]]
    assert [trace.customdata[0][0][0] for trace in fig.data[:3]] == [
        'A-No Rework', 'A-1 Rework', 'A-2 Reworks']
    assert list(fig.data[-1].y) == ['<b>Total</b>']
    assert list(fig.data[-1].z[0]) == [3, 110, None]
    assert fig.data[-1].colorscale[0][1] == fig.data[-1].colorscale[-1][1]
    assert fig.layout.meta['color_scope'] == 'per_column'
    assert fig.layout.meta['column_maxima'] == [2, 100, 0]
    assert fig.layout.meta['column_totals'] == [3, 110, None]
    assert all(trace.showscale is False for trace in fig.data)
    assert len(fig.layout.annotations) == 9
    fig.to_json()


@pytest.mark.parametrize('dark', [False, True])
def test_huge_tier_does_not_dim_other_column_or_change_labels(dark):
    baseline = render(100, dark=dark, counts=True)
    changed = render(10000, dark=dark, counts=True)
    assert baseline.data[0].zmax == changed.data[0].zmax == 2
    assert baseline.data[0].colorscale == changed.data[0].colorscale
    assert baseline.data[0].hoverlabel.bgcolor == changed.data[0].hoverlabel.bgcolor
    assert baseline.data[1].zmax == 100
    assert changed.data[1].zmax == 10000
    assert [a.text for a in baseline.layout.annotations if a.x == 'No Rework'] == [
        a.text for a in changed.layout.annotations if a.x == 'No Rework']
    assert baseline.layout.meta['column_totals'][0] == changed.layout.meta['column_totals'][0] == 3
    assert ' / 1' in baseline.layout.annotations[0].text


def test_no_total_row_still_uses_per_column_maxima():
    fig = render(with_total=False)
    assert len(fig.data) == 3
    assert fig.layout.meta['column_totals'] is None
    assert fig.layout.meta['column_maxima'] == [2, 100, 0]
    assert [trace.zmax for trace in fig.data] == [2, 100, 1]

"""Column-local heatmap color without separate Plotly cell geometry."""
import pytest

from slicing_dashboard.plots.intensity_chart import intensity_chart


def fixture(hours_b=100, *, with_total=True):
    users = ['A', 'B'] + (['<b>Total</b>'] if with_total else [])
    categories = ['No Rework', '1 Rework', '2 Reworks']
    values = [[1.0, float(hours_b), None], [2.0, 10.0, 0.0]]
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
def test_all_categories_and_total_use_one_aligned_matrix(dark):
    fig = render(dark=dark)
    assert len(fig.data) == 1  # no detached one-column or one-row Heatmaps
    trace = fig.data[0]
    assert list(trace.x) == ['No Rework', '1 Rework', '2 Reworks']
    assert list(trace.y) == ['A', 'B', '<b>Total</b>']
    assert [list(row) for row in trace.z] == [
        [.5, 1, None], [1, .1, 0], [-1, -1, -1]]
    assert trace.zmin == -1 and trace.zmax == 1
    assert list(trace.customdata[0][0]) == ['A-No Rework', 0, 1.0]
    assert trace.customdata[1][1][-1] == 10.0
    assert [cell[-1] for cell in trace.customdata[-1]] == [3.0, 110.0, None]
    assert trace.colorscale[0][1] == trace.colorscale[1][1]  # neutral Total band
    assert fig.layout.meta['color_scope'] == 'per_column'
    assert fig.layout.meta['single_aligned_matrix'] is True
    assert fig.layout.meta['column_maxima'] == [2, 100, 0]
    assert fig.layout.meta['column_totals'] == [3, 110, None]
    assert trace.showscale is False
    assert len(fig.layout.annotations) == 9
    fig.to_json()


@pytest.mark.parametrize('dark', [False, True])
def test_huge_tier_changes_only_its_own_column_color(dark):
    baseline = render(100, dark=dark, counts=True)
    changed = render(10000, dark=dark, counts=True)
    a, b = baseline.data[0], changed.data[0]
    assert [row[0] for row in a.z] == [row[0] for row in b.z] == [.5, 1, -1]
    assert [row[1] for row in a.z] == [1, .1, -1]
    assert [row[1] for row in b.z] == [1, .001, -1]
    assert [row[0] for row in a.hoverlabel.bgcolor] == [
        row[0] for row in b.hoverlabel.bgcolor]
    assert [annotation.text for annotation in baseline.layout.annotations
            if annotation.x == 'No Rework'] == [
        annotation.text for annotation in changed.layout.annotations
        if annotation.x == 'No Rework']
    assert a.customdata[0][1][-1] == 100
    assert b.customdata[0][1][-1] == 10000
    assert baseline.layout.meta['column_totals'][0] == changed.layout.meta['column_totals'][0] == 3
    assert ' / 1' in baseline.layout.annotations[0].text


def test_no_total_row_keeps_one_matrix_and_no_neutral_reserved_band():
    fig = render(with_total=False)
    assert len(fig.data) == 1
    assert list(fig.data[0].y) == ['A', 'B']
    assert fig.data[0].zmin == 0 and fig.data[0].zmax == 1
    assert fig.layout.meta['column_totals'] is None
    assert fig.layout.meta['column_maxima'] == [2, 100, 0]
    assert [list(row) for row in fig.data[0].z] == [[.5, 1, None], [1, .1, 0]]

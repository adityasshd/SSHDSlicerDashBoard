"""Check the rendered dashboard in the synthetic local QA server."""
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


GROUPS = {
    'Completed duration': ('individual-chart', 'universal-legend'),
    'Submissions & review': ('today-submissions-lollipop-chart', 'review-workload-chart'),
    'Rework & pending': ('rework-ratio-chart', 'pending-chart'),
    'Assigned work': ('assigned-chart',),
    'Return reasons': ('return-reasons-chart',),
}


def check_layout(page):
    previews = Path('dashboard-layout-preview')
    previews.mkdir(exist_ok=True)
    origin = 'http://127.0.0.1:8059'
    response = page.request.post(origin + '/qa/scenario', data={
        'mode': 'tiers', 'team_size': 8, 'pending_limit': 8, 'seed_panels': True,
    })
    assert response.ok
    page.emulate_media(color_scheme='light')
    page.goto(origin)
    for width, height in [(1024, 640), (1366, 768), (1440, 900), (1920, 1080)]:
        page.set_viewport_size({'width': width, 'height': height})
        for name, ids in GROUPS.items():
            page.get_by_role('radio', name=name, exact=True).check()
            for chart in ids:
                expect(page.locator('#' + chart)).to_be_visible()
                page.wait_for_function("""id => {
                    const el = document.getElementById(id);
                    const fig = el.querySelector('.js-plotly-plot')?._fullLayout;
                    return fig && fig._size.h >= 140 &&
                        Math.abs(fig.width - el.clientWidth) < 3;
                }""", arg=chart)
            size = page.evaluate('''() => [document.documentElement.scrollWidth,
                document.documentElement.scrollHeight]''')
            print(f'{width}x{height} / {name}: {size}', flush=True)
            assert size[0] <= width and size[1] <= 2 * height, (name, width, height, size)
            if width == 1366:
                page.screenshot(path=previews / f'{ids[0]}.png', full_page=True)
    page.emulate_media(media='print')
    for ids in GROUPS.values():
        for chart in ids:
            expect(page.locator('#' + chart)).to_be_visible()
    assert page.pdf(path=previews / 'overview.pdf', prefer_css_page_size=True).startswith(b'%PDF')
    page.emulate_media(media='screen')
    page.set_viewport_size({'width': 390, 'height': 844})
    for ids in GROUPS.values():
        for chart in ids:
            expect(page.locator('#' + chart)).to_be_visible()


if __name__ == '__main__':
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome')
        try:
            check_layout(browser.new_page())
        finally:
            browser.close()

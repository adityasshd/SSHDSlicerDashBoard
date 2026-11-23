const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const asset = fs.readFileSync(
    path.join(__dirname, '../src/slicing_dashboard/assets/theme.js'), 'utf8'
).split('// Report graphs are mounted while their route is hidden.')[0];

function start({systemDark = false, stored = null} = {}) {
    let saved = stored;
    let theme = '';
    let listener;
    const props = [];
    const classes = new Set(['theme-system']);
    const shell = {
        classList: {
            toggle(name, condition) { if (condition) classes.add(name); else classes.delete(name); },
            remove(name) { classes.delete(name); }
        }
    };
    const button = {setAttribute() {}};
    const document = {
        documentElement: {setAttribute(key, value) { if (key === 'data-bs-theme') theme = value; }},
        getElementById(id) { return id === 'main-container' ? shell : id === 'theme-toggle' ? button : null; }
    };
    const media = {
        matches: systemDark,
        addEventListener(event, handler) { if (event === 'change') listener = handler; },
        setSystem(dark) { this.matches = dark; listener(); }
    };
    const window = {
        matchMedia() { return media; },
        localStorage: {
            getItem() { return saved; },
            setItem(key, value) { assert.equal(key, 'sshd-slicing-theme-preference'); saved = value; }
        },
        dash_clientside: {set_props(id, value) { props.push({id, value}); }}
    };
    vm.runInNewContext(asset, {window, document});
    return {
        click: window.dash_clientside.clientside.toggleTheme,
        media, props, classes,
        currentTheme: () => theme,
        savedChoice: () => saved,
        resetPreference() { saved = null; }
    };
}

test('first render follows OS light mode and does not store a manual choice', () => {
    const app = start({systemDark: false});
    assert.equal(app.click(0), 1);
    assert.equal(app.currentTheme(), 'light');
    assert.equal(app.savedChoice(), null);
    assert.ok(app.classes.has('theme-light'));
});

test('first render follows OS dark mode', () => {
    const app = start({systemDark: true});
    assert.equal(app.click(0), 0);
    assert.equal(app.currentTheme(), 'dark');
});

test('manual toggle persists across reload and suppresses later system changes', () => {
    const app = start({systemDark: false});
    app.click(0);
    assert.equal(app.click(1), 0);
    assert.equal(app.savedChoice(), 'dark');
    app.media.setSystem(true);
    app.media.setSystem(false);
    assert.equal(app.currentTheme(), 'dark');
    assert.equal(app.props.length, 0);
    const reopened = start({systemDark: false, stored: app.savedChoice()});
    assert.equal(reopened.click(0), 0);
});

test('system changes repaint charts when there is no override', () => {
    const app = start({systemDark: false});
    app.click(0);
    app.media.setSystem(true);
    assert.equal(app.currentTheme(), 'dark');
    assert.equal(JSON.stringify(app.props.at(-1)), JSON.stringify({id: 'theme-effective-count', value: {data: 0}}));
    app.media.setSystem(false);
    assert.equal(app.currentTheme(), 'light');
    assert.equal(JSON.stringify(app.props.at(-1)), JSON.stringify({id: 'theme-effective-count', value: {data: 1}}));
});

test('desktop detail selection is screen-only and preserves data-driven chart heights', () => {
    const css = fs.readFileSync(path.join(__dirname, '../src/slicing_dashboard/assets/style_v2.css'), 'utf8');
    const desktop = css.slice(css.indexOf('@media screen and (min-width: 1024px)'), css.indexOf('@page slicing-overview'));
    for (const view of ['completed', 'matrices', 'assigned', 'reasons']) {
        assert.ok(desktop.includes('#dashboard-page.view-' + view));
    }
    assert.doesNotMatch(css, /height:\s*(185|205|215)px !important/);
    assert.match(css, /break-inside: avoid/);
});

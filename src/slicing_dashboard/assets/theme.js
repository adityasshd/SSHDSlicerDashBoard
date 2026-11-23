// Resolve the system theme at startup; persist only an explicit button override.
(function () {
    const KEY = 'sshd-slicing-theme-preference';
    const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    let previousClicks = null;
    let sessionOverride = null;

    function manualPreference() {
        try {
            const saved = window.localStorage.getItem(KEY);
            return saved === 'light' || saved === 'dark' ? saved : null;
        } catch (error) {
            return sessionOverride;
        }
    }
    function currentTheme() {
        return manualPreference() || (media && !media.matches ? 'light' : 'dark');
    }
    function applyTheme(mode) {
        document.documentElement.setAttribute('data-bs-theme', mode);
        const shell = document.getElementById('main-container');
        if (shell) {
            shell.classList.toggle('theme-dark', mode === 'dark');
            shell.classList.toggle('theme-light', mode === 'light');
            shell.classList.remove('theme-system');
        }
        const button = document.getElementById('theme-toggle');
        if (button) {
            const label = mode === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
            button.setAttribute('aria-label', label);
            button.setAttribute('title', label);
        }
    }
    function toggleTheme(clicks) {
        const count = Number.isFinite(Number(clicks)) ? Number(clicks) : 0;
        // Initial Dash invocation is NOT a manual choice.
        if (previousClicks !== null && count > previousClicks) {
            const next = currentTheme() === 'dark' ? 'light' : 'dark';
            sessionOverride = next;
            try { window.localStorage.setItem(KEY, next); } catch (error) { /* session fallback */ }
        }
        previousClicks = count;
        const effective = currentTheme();
        applyTheme(effective);
        // Existing Python figures use even = dark, odd = light.
        return effective === 'dark' ? 0 : 1;
    }

    // System changes remain live until a manual override is stored.
    function followSystem() {
        if (manualPreference()) return;
        const mode = currentTheme();
        applyTheme(mode);
        if (window.dash_clientside && typeof window.dash_clientside.set_props === 'function') {
            window.dash_clientside.set_props('theme-effective-count', {
                data: mode === 'dark' ? 0 : 1
            });
        }
    }
    if (media) {
        if (typeof media.addEventListener === 'function') media.addEventListener('change', followSystem);
        else if (typeof media.addListener === 'function') media.addListener(followSystem);
    }
    applyTheme(currentTheme());
    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.clientside = Object.assign(
        {}, window.dash_clientside.clientside, {toggleTheme: toggleTheme}
    );
})();

// Report graphs are mounted while their route is hidden. Plotly needs the
// visible container size after route changes, and after a new figure arrives.
(function () {
    const observed = new WeakSet();
    const sizes = new WeakMap();
    const observer = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
            const box = entry.contentRect;
            if (!box.width || !box.height) {
                sizes.set(entry.target, [0, 0]);
                return;
            }
            const previous = sizes.get(entry.target);
            if (previous && previous[0] === box.width && previous[1] === box.height) return;
            sizes.set(entry.target, [box.width, box.height]);
            requestAnimationFrame(function () {
                const plot = entry.target.querySelector('.js-plotly-plot');
                if (plot && plot.data && window.Plotly) window.Plotly.Plots.resize(plot);
            });
        });
    });
    function watchGraphs(root = document) {
        const graphs = root.matches?.('.dash-graph') ? [root] : root.querySelectorAll('.dash-graph');
        graphs.forEach(function (graph) {
            if (!observed.has(graph)) {
                observed.add(graph);
                observer.observe(graph);
            }
        });
    }
    function start() {
        watchGraphs();
        let scheduled = false;
        const roots = new Set();
        new MutationObserver(function (records) {
            records.forEach(function (record) {
                if (record.target.closest?.('.dash-graph')) return;
                record.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1 && (node.matches('.dash-graph') ||
                        node.querySelector('.dash-graph'))) roots.add(node);
                });
            });
            if (scheduled || !roots.size) return;
            scheduled = true;
            requestAnimationFrame(function () {
                scheduled = false;
                for (const root of roots) if (root.isConnected) watchGraphs(root);
                roots.clear();
            });
        }).observe(document.body, {childList: true, subtree: true});
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();

// Auto-open date picker when clicking anywhere on the date input field
document.addEventListener('click', function(e) {
    if (e.target && e.target.classList && e.target.classList.contains('date-input-custom')) {
        if (typeof e.target.showPicker === 'function') {
            try {
                e.target.showPicker();
            } catch (err) {
                // Ignore if already open or not supported
            }
        }
    }
});

// Keep dense charts readable without blocking page scrolling or building hidden tables.
(function () {
    const bound = new WeakSet();
    let tooltip;
    function clock(hours, compact) {
        const seconds = Math.round(hours * 3600);
        const pad = value => String(value).padStart(2, '0');
        const label = `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor(seconds % 3600 / 60))}`;
        return compact ? label : `${label}:${pad(seconds % 60)}`;
    }
    function durationTicks(lower, upper) {
        lower = Math.max(0, lower);
        if (!Number.isFinite(lower) || !Number.isFinite(upper) || upper <= lower) return [[], []];
        const span = upper - lower, unit = span < 1 / 60 ? 1 / 3600 : span < 1 ? 1 / 60 : 1;
        const target = span / unit / 5, magnitude = 10 ** Math.floor(Math.log10(target));
        const step = [1, 2, 5, 10].find(scale => scale * magnitude >= target) * magnitude * unit;
        const first = Math.ceil(lower / step), values = [];
        for (let index = 0; index < 7; index++) {
            const value = (first + index) * step;
            if (value <= upper) values.push(value);
        }
        return [values, values.map(value => clock(value, step * 3600 >= 60))];
    }
    function setDurationTicks(update, axis, lower, upper) {
        const [values, labels] = durationTicks(lower, upper);
        update[`${axis}.tickmode`] = 'array';
        update[`${axis}.tickvals`] = values;
        update[`${axis}.ticktext`] = labels;
    }
    function refreshHourLabels(plot) {
        const orientation = plot.layout.meta?.hour_axis_orientation;
        if (!orientation || !window.Plotly) return;
        const horizontal = orientation === 'h', totals = new Map();
        let maximum = 0;
        const stacked = ['stack', 'relative'].includes(plot.layout.barmode);
        for (const trace of plot._fullData || []) {
            if (trace.visible === false || trace.visible === 'legendonly') continue;
            const values = horizontal ? trace.x : trace.y;
            const labels = horizontal ? trace.y : trace.x;
            Array.from(values || []).forEach((value, index) => {
                const valid = typeof value === 'number' && Number.isFinite(value) && value >= 0;
                if (valid) maximum = Math.max(maximum, value);
                if (trace.type !== 'bar' || !labels) return;
                const key = labels[index], previous = totals.has(key) ? totals.get(key) : 0;
                totals.set(key, valid && previous !== null ? previous + value : null);
            });
        }
        if (stacked) for (const value of totals.values()) if (value !== null) maximum = Math.max(maximum, value);
        const upper = maximum > 0 ? maximum * 1.1 : 1;
        if (!Number.isFinite(upper)) return;
        const update = {[`${horizontal ? 'x' : 'y'}axis.range`]: [0, upper],
                        [`${horizontal ? 'x' : 'y'}axis.autorange`]: false};
        setDurationTicks(update, `${horizontal ? 'x' : 'y'}axis`, 0, upper);
        if (plot.layout.meta.bar_total_labels) {
            const annotations = (plot.layout.annotations || []).filter(item => item.name !== 'bar-hour-total');
            for (const [category, total] of totals) {
                if (total === null) continue;
                const label = clock(total, total === 0 || total >= 1 / 60);
                annotations.push({name: 'bar-hour-total', text: label,
                    x: horizontal ? total : category, y: horizontal ? category : total,
                    xref: 'x', yref: 'y', showarrow: false,
                    xanchor: horizontal ? 'left' : 'center', yanchor: horizontal ? 'middle' : 'bottom',
                    xshift: horizontal ? 6 : 0, yshift: horizontal ? 0 : 6,
                    font: {size: 11, color: plot.layout.font?.color}});
            }
            update.annotations = annotations;
        }
        window.Plotly.relayout(plot, update);
    }
    function hideTooltip() { if (tooltip) tooltip.hidden = true; }
    function styleBars(plot) {
        const traces = (plot._fullData || []).filter(trace => trace.type === 'bar' && trace.visible === true);
        if (!traces.length || !window.Plotly) return;
        const horizontal = traces[0].orientation === 'h';
        const axis = plot._fullLayout?.[horizontal ? 'yaxis' : 'xaxis'];
        if (!axis?._length || !axis.range) return;
        const range = axis.range.map(value => axis.type === 'date' ? Date.parse(value) : Number(value));
        const span = Math.abs(range[1] - range[0]);
        if (!Number.isFinite(span) || !span) return;
        const maxPixels = horizontal ? 18 : 24;
        let width = maxPixels * span / axis._length;
        if (axis.type === 'category') {
            const overlaps = new Map();
            if (plot._fullLayout.barmode === 'group') {
                traces.forEach(trace => Array.from(new Set(trace[horizontal ? 'y' : 'x'] || [])).forEach(category =>
                    overlaps.set(category, (overlaps.get(category) || 0) + 1)));
            }
            const groups = Math.max(1, ...overlaps.values());
            width = Math.min(width, .55 / groups);
        }
        const changed = traces.filter(trace => typeof trace.width !== 'number' || Math.abs(trace.width - width) > width * .005);
        if (changed.length) {
            window.Plotly.restyle(plot, {width}, changed.map(trace => trace.index));
            return;
        }
        // Clip the outside of the whole stack to a capsule. Internal stage joins
        // stay square, while the baseline and the far end share the same radius.
        const svgNS = 'http://www.w3.org/2000/svg';
        const defs = plot.querySelector('defs');
        if (!defs) return;
        defs.querySelector('[data-dashboard-capsules]')?.remove();
        const container = document.createElementNS(svgNS, 'g');
        container.setAttribute('data-dashboard-capsules', 'true');
        defs.appendChild(container);
        const groups = new Map();
        plot.querySelectorAll('.barlayer .point path').forEach(path => {
            const box = path.getBBox();
            if (!box.width || !box.height) return;
            const center = horizontal ? box.y + box.height / 2 : box.x + box.width / 2;
            const key = Math.round(center * 100);
            const group = groups.get(key) || {paths: [], left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity};
            group.paths.push(path);
            group.left = Math.min(group.left, box.x); group.top = Math.min(group.top, box.y);
            group.right = Math.max(group.right, box.x + box.width); group.bottom = Math.max(group.bottom, box.y + box.height);
            groups.set(key, group);
        });
        let index = 0;
        groups.forEach(group => {
            const id = `dashboard-capsule-${plot._fullLayout._uid}-${index++}`;
            const clip = document.createElementNS(svgNS, 'clipPath');
            clip.setAttribute('id', id); clip.setAttribute('clipPathUnits', 'userSpaceOnUse');
            const rect = document.createElementNS(svgNS, 'rect');
            const w = group.right - group.left, h = group.bottom - group.top;
            for (const [key, value] of Object.entries({x: group.left, y: group.top, width: w, height: h, rx: Math.min(w, h) / 2}))
                rect.setAttribute(key, String(value));
            clip.appendChild(rect); container.appendChild(clip);
            group.paths.forEach(path => {
                path.setAttribute('clip-path', `url(#${id})`);
                path.style.shapeRendering = 'geometricPrecision';
            });
        });
    }
    function update(plot, graph) {
        const frame = graph.closest('.chart-frame');
        if (!frame || !plot.data) return;
        const traces = plot._fullData || plot.data;
        const horizontal = new Set();
        traces.forEach(trace => {
            if (trace.type !== 'bar') return;
            if (trace.orientation !== 'h' && plot._fullLayout?.xaxis?.type === 'date') return;
            if (trace.orientation !== 'h') return;
            Array.from((trace.orientation === 'h' ? trace.y : trace.x) || []).forEach(value => {
                if (typeof value === 'string') horizontal.add(value);
            });
        });
        if (!graph.dataset.baseHeight) graph.dataset.baseHeight = String(parseFloat(graph.style.height) || 340);
        const legend = plot._fullLayout?.legend;
        const items = traces.filter(trace => trace.showlegend !== false && trace.name).length;
        const horizontalLegend = plot._fullLayout?.showlegend && legend?.orientation === 'h' && items;
        // Reserve real space for wrapped legends as the card narrows. Keep the
        // plotting area stable instead of clipping the legend into a tiny box.
        const columns = Math.max(1, Math.floor((plot._fullLayout?._size?.w || frame.clientWidth - 80) / 150));
        const bottom = horizontalLegend ? Math.max(100, Math.min(390, Math.ceil(items / columns) * 32 + 50)) : 0;
        const extra = horizontalLegend ? bottom - 100 : 0;
        const height = Math.max(Number(graph.dataset.baseHeight) + extra, horizontal.size * 34 + 160 + extra);
        // The shared ResizeObserver handles changed dimensions once.
        if (graph.style.height !== height + 'px') graph.style.height = height + 'px';
        if (graph.style.width !== '100%') graph.style.width = '100%';
        if (horizontalLegend && window.Plotly &&
            (plot.layout.margin?.b !== bottom || plot.layout.legend?.maxheight !== bottom - 24)) {
            window.Plotly.relayout(plot, {'margin.b': bottom, 'legend.maxheight': bottom - 24});
        }
    }
    function watch(root = document) {
        const plots = root.matches?.('.js-plotly-plot') ? [root] :
            root.querySelectorAll('.chart-surface .js-plotly-plot');
        plots.forEach(plot => {
            if (bound.has(plot) || typeof plot.on !== 'function') return;
            const graph = plot.closest('.chart-surface');
            if (!graph) return;
            bound.add(plot);
            plot.on('plotly_afterplot', () => update(plot, graph));
            plot.on('plotly_afterplot', () => styleBars(plot));
            plot.on('plotly_restyle', () => refreshHourLabels(plot));
            plot.on('plotly_relayout', event => {
                const coordinate = plot.layout.meta?.duration_axis_orientation;
                if (!coordinate || !window.Plotly) return;
                const axis = `${coordinate}axis`;
                if (!Object.keys(event).some(key => key.startsWith(`${axis}.range`) || key === `${axis}.autorange`)) return;
                const range = plot._fullLayout?.[axis]?.range;
                if (!range) return;
                const update = {};
                setDurationTicks(update, axis, range[0], range[1]);
                window.Plotly.relayout(plot, update);
            });
            plot.on('plotly_unhover', hideTooltip);
            plot.on('plotly_hover', event => {
                requestAnimationFrame(() => {
                    const hover = plot.querySelector('.hoverlayer');
                    const lines = hover ? Array.from(hover.querySelectorAll('text')).map(node => {
                        const parts = Array.from(node.querySelectorAll('tspan.line'));
                        return parts.length ? parts.map(part => part.textContent).join('\n') : node.textContent;
                    }) : [];
                    if (!lines.length) return;
                    if (!tooltip) {
                        tooltip = document.createElement('div'); tooltip.className = 'chart-tooltip';
                        tooltip.setAttribute('role', 'tooltip'); document.body.appendChild(tooltip);
                    }
                    tooltip.textContent = lines.join('\n');
                    tooltip.hidden = false;
                    const rect = tooltip.getBoundingClientRect();
                    const pointer = event.event || {};
                    tooltip.style.left = Math.max(12, Math.min((pointer.clientX || 12) + 14, innerWidth - rect.width - 12)) + 'px';
                    tooltip.style.top = Math.max(12, Math.min((pointer.clientY || 12) + 14, innerHeight - rect.height - 12)) + 'px';
                    plot.classList.add('bounded-hover');
                });
            });
            update(plot, graph);
            styleBars(plot);
        });
    }
    function start() {
        let queued = false;
        const roots = new Set();
        new MutationObserver(records => {
            for (const record of records) {
                const plot = record.target.closest?.('.js-plotly-plot');
                // Plotly redraws and hover updates are already covered by its events.
                if (plot) {
                    if (!bound.has(plot)) roots.add(plot);
                    continue;
                }
                for (const node of record.addedNodes) {
                    if (node.nodeType === 1 && (node.matches('.js-plotly-plot') ||
                        node.querySelector('.chart-surface, .js-plotly-plot'))) roots.add(node);
                }
            }
            if (queued || !roots.size) return;
            queued = true;
            requestAnimationFrame(() => {
                queued = false;
                for (const root of roots) if (root.isConnected) watch(root);
                roots.clear();
            });
        }).observe(document.body, {childList: true, subtree: true});
        document.addEventListener('scroll', hideTooltip, true);
        window.addEventListener('resize', hideTooltip);
        watch();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();

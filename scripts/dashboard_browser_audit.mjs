// Standalone headless fallback when the in-app browser cannot connect.
// Runs only against scripts/dashboard_chart_preview.py's synthetic localhost fixture.
import {spawn} from 'node:child_process';
import {mkdir, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const qaOrigin = process.argv[3] || process.env.DASHBOARD_QA_ORIGIN || 'http://127.0.0.1:8059';
const qaFetch = (url, options) => fetch(url.replace('http://127.0.0.1:8059', qaOrigin), options);

const root = resolve('data/reports/chart-qa');
await mkdir(root, {recursive: true});
const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
    '--headless=new', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
    `--user-data-dir=${root}/browser-profile`, 'about:blank'], {windowsHide: true});
const endpoint = await new Promise((accept, reject) => {
    let buffer = '';
    chrome.stderr.on('data', value => {
        buffer += value;
        const match = buffer.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (match) accept(match[1]);
    });
    chrome.on('error', reject);
    setTimeout(() => reject(new Error('Browser startup timeout')), 15000).unref();
});
const ws = new WebSocket(endpoint);
await new Promise((accept, reject) => { ws.onopen = accept; ws.onerror = reject; });
let sequence = 0;
const pending = new Map();
const errors = [];
const callbackRequests = [];
ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
        const handler = pending.get(message.id);
        if (!handler) return;
        pending.delete(message.id);
        message.error ? handler.reject(new Error(JSON.stringify(message.error))) : handler.accept(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails);
    else if (message.method === 'Network.responseReceived' && message.params.response.status >= 400)
        errors.push({url: message.params.response.url, status: message.params.response.status});
    else if (message.method === 'Network.requestWillBeSent' && message.params.request.url.endsWith('/_dash-update-component')) {
        const body = JSON.parse(message.params.request.postData || '{}');
        callbackRequests.push({output: body.output, at: Date.now()});
    }
};
function send(method, params = {}, sessionId) {
    return new Promise((accept, reject) => {
        const id = ++sequence;
        pending.set(id, {accept, reject});
        ws.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
    });
}
const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
const call = (method, params) => send(method, method === 'Page.navigate' ?
    {...params, url: params.url.replace('http://127.0.0.1:8059', qaOrigin)} : params, sessionId);
await call('Runtime.enable');
await call('Page.enable');
await call('Network.enable');
async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
}
async function until(expression, timeout = 20000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
        if (await evaluate(expression)) return;
        await new Promise(accept => setTimeout(accept, 150));
    }
    throw new Error('Timed out: ' + expression);
}
const visible = `el => !!(el.offsetWidth && el.offsetHeight && el.getClientRects().length)`;
const results = [];
try {
    if (process.argv[2] === 'local') {
        await call('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 2, mobile: false});
        await call('Page.navigate', {url: qaOrigin + '/'});
        await until(`!!document.querySelector('#approval-trend-chart .js-plotly-plot')`, 45000);
        await until(`document.querySelector('#approval-trend-chart .js-plotly-plot')?.layout?.meta?.primary_metric === 'completed'`, 60000);
        const local = await evaluate(`(() => {
            const g=document.querySelector('#approval-trend-chart'),p=g.querySelector('.js-plotly-plot');
            return {from:document.querySelector('#date-from')?.value,to:document.querySelector('#date-to')?.value,
                graph:g.getBoundingClientRect().toJSON(),plot:p._fullLayout?._size,theme:document.querySelector('#main-container').className,
                metric:p.layout?.meta?.primary_metric,
                traces:(p.data||[]).map(t=>({name:t.name,points:t.y?.length,valid:Array.from(t.y||[]).filter(v=>v!==null&&Number.isFinite(v)).length,shape:t.line?.shape})),
                annotations:(p.layout?.annotations||[]).map(a=>a.text),status:document.querySelector('#approval-trend-status').textContent,
                axes:{x:p.layout?.xaxis,y:p.layout?.yaxis},errors:document.querySelectorAll('.dash-error-card').length};})()`);
        console.log(JSON.stringify(local));results.push(local);
        if (local.metric !== 'completed' || local.traces.length !== 1 || !local.traces[0].valid || local.traces[0].shape !== 'spline' || local.errors)
            throw new Error('Completed video did not render as a single populated spline');
        const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
        await writeFile(`${root}/actual-local.png`,Buffer.from(screenshot.data,'base64'));
        for (const theme of ['dark', 'light']) {
            if (theme === 'light') {
                await evaluate(`document.querySelector('#theme-toggle').click()`);
                await until(`document.querySelector('#approval-trend-chart .js-plotly-plot')?.layout?.font?.color === '#354039'`);
            }
            const viewport=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
            await writeFile(`${root}/actual-${theme}.png`,Buffer.from(viewport.data,'base64'));
        }
    }
    if (process.argv[2] === 'modernization') {
        const lead = `document.querySelector('#approval-trend-chart .js-plotly-plot')`;
        for (const pattern of ['varied', 'single', 'empty']) {
            await qaFetch(qaOrigin + '/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mode: 'normal', trend_pattern: pattern, auditor_seconds: 1800, admin_seconds: 900})});
            for (const width of (pattern === 'varied' ? [390, 1366, 1920] : [1366])) {
                await call('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 2, mobile: false});
                await call('Page.navigate', {url: qaOrigin + '/'});
                await until(`${lead}?.layout?.meta?.chart_role === 'primary-trend' && document.querySelector('#review-workload-chart .js-plotly-plot')?.data?.[0]?.type === 'pie' && document.querySelector('#approval-progression-chart .js-plotly-plot')?.data?.[0]?.type === 'funnel'`);
                for (const theme of ['dark', 'light']) {
                    if (theme === 'light') {
                        await evaluate(`document.querySelector('#theme-toggle').click()`);
                        await until(`document.querySelector('#main-container').className === 'theme-light' && ${lead}.layout.font.color === '#354039'`);
                    }
                    await until(`!Array.from(document.querySelectorAll('[data-dash-is-loading="true"]')).some(${visible})`);
                    await until(`['approval-trend-chart','approval-progression-chart','review-workload-chart','return-reasons-chart'].every(id=>document.querySelector('#'+id+' .js-plotly-plot')?.layout?.font?.color === '${theme === 'light' ? '#354039' : '#ccd0ce'}')`);
                    const view = await evaluate(`(() => {
                        const p=${lead}, g=document.querySelector('#approval-trend-chart'), r=g.getBoundingClientRect();
                        const markers=Array.from(p.querySelectorAll('.scatterlayer .point'));
                        const bars=document.querySelector('#individual-chart .js-plotly-plot');
                        const donut=document.querySelector('#review-workload-chart .js-plotly-plot');
                        const funnel=document.querySelector('#approval-progression-chart .js-plotly-plot');
                        return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,plotHeight:p._fullLayout._size.h,
                            markerCount:markers.length,recorded:p.layout.meta.recorded_days,
                            markerClipped:markers.some(el=>{const b=el.getBoundingClientRect();return b.left<r.left-1||b.right>r.right+1||b.top<r.top-1||b.bottom>r.bottom+1}),
                            primaryValues:p.data[0].y,annotations:(p.layout.annotations||[]).map(a=>a.text),
                            lineColor:p.data[0].line.color,barRadius:bars.layout.barcornerradius,
                            roundedPaths:Array.from(bars.querySelectorAll('.point path')).some(el=>/[AQaq]/.test(el.getAttribute('d'))),
                            capsules:Array.from(bars.querySelectorAll('[data-dashboard-capsules] rect')).map(el=>({
                                width:Number(el.getAttribute('width')),height:Number(el.getAttribute('height')),radius:Number(el.getAttribute('rx'))})),
                            donut:donut.data[0].type,funnel:funnel.data[0].type,
                            paper:getComputedStyle(document.querySelector('.dashboard-lead')).backgroundColor};
                    })()`);
                    if (view.documentWidth > width + 1 || view.plotHeight < 250 || view.markerClipped || view.barRadius !== 7 || !view.roundedPaths)
                        throw new Error('Line visibility, rounded bars, or container sizing failed: '+JSON.stringify(view));
                    if (!view.capsules.length || view.capsules.some(c=>c.width>24.5 || Math.abs(c.radius-Math.min(c.width,c.height)/2)>.01))
                        throw new Error('Bars must be narrow capsules rounded at both ends: '+JSON.stringify(view.capsules));
                    if ((pattern !== 'empty' && view.markerCount !== view.recorded) || (pattern === 'empty' && !view.annotations.length))
                        throw new Error('Sparse/empty trend state is not visible');
                    if (theme === 'light' && (view.lineColor !== '#165a50' || view.paper !== 'rgb(255, 255, 255)'))
                        throw new Error('Light theme did not update chart and card together');
                    results.push({width, theme, pattern, ...view});
                    await evaluate(`window.scrollTo(0,0)`);
                    const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
                    await writeFile(`${root}/modern-${theme}-${pattern}-${width}.png`,Buffer.from(screenshot.data,'base64'));
                    console.log(JSON.stringify({width,theme,pattern,markers:view.markerCount,plotHeight:view.plotHeight,rounded:view.roundedPaths}));
                }
            }
        }
    }
    if (process.argv[2] === 'controls') {
        await qaFetch(qaOrigin + '/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'normal'})});
        await call('Page.navigate', {url: qaOrigin + '/'});
        await until(`document.querySelector('#settlement-dropdown') && document.querySelector('#main-container').className === 'theme-dark'`);
        await evaluate(`document.querySelector('#settlement-dropdown').click()`);
        await until(`!!document.querySelector('[role="listbox"]')`);
        const control = await evaluate(`(() => {
            const dropdown = document.querySelector('#settlement-dropdown'), menu = document.querySelector('[role="listbox"]');
            return {trigger: {background: getComputedStyle(dropdown).backgroundColor, color: getComputedStyle(dropdown).color},
                menu: {background: getComputedStyle(menu).backgroundColor, color: getComputedStyle(menu).color},
                search: {background: getComputedStyle(document.querySelector('.dash-dropdown-content input')).backgroundColor}};
        })()`);
        results.push({control});
        console.log(JSON.stringify(control));
        if (control.trigger.background === 'rgb(255, 255, 255)' || control.search.background === 'rgb(255, 255, 255)')
            throw new Error('White dropdown control in dark theme');
        const screenshot = await call('Page.captureScreenshot', {format: 'png'});
        await writeFile(`${root}/dark-controls.png`, Buffer.from(screenshot.data, 'base64'));
    }
    if (process.argv[2] === 'rework') {
        await qaFetch(qaOrigin + '/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'tiers', seed_panels: true})});
        const rework = `document.querySelector('#rework-ratio-chart .js-plotly-plot')`;
        for (const width of [390, 1366]) {
            await call('Emulation.setDeviceMetricsOverride', {width, height: 950, deviceScaleFactor: 1, mobile: false});
            await call('Page.navigate', {url: qaOrigin + '/'});
            await until(`${rework}?.data?.[3]?.customdata?.[0]?.[6] === '15:00:00'`);
            await evaluate(`document.querySelector('#rework-ratio-chart').scrollIntoView({block:'center',behavior:'instant'})`);
            const hovers = [];
            for (const [index, hours] of ['01:00:00', '02:00:00', '03:00:00', '15:00:00'].entries()) {
                const pointer = await evaluate(`(() => {
                    const r = ${rework}.querySelectorAll('.trace.bars')[${index}].querySelector('.point path').getBoundingClientRect();
                    return {x: r.left + r.width / 2, y: r.top + r.height / 2};
                })()`);
                await call('Input.dispatchMouseEvent', {type: 'mouseMoved', ...pointer});
                await until(`document.querySelector('.chart-tooltip:not([hidden])')?.textContent.includes('Duration: ${hours}')`);
                const text = await evaluate(`document.querySelector('.chart-tooltip:not([hidden])').textContent`);
                if ((text.match(/Duration:/g) || []).length !== 1 || text.includes('21:00:00'))
                    throw new Error('Rework hover contains unrelated stack hours');
                hovers.push(text);
            }
            const screenshot = await call('Page.captureScreenshot', {format: 'png'});
            await writeFile(`${root}/rework-hover-${width}.png`, Buffer.from(screenshot.data, 'base64'));
            results.push({width, hovers});
            console.log(JSON.stringify({width, hovers}));
        }
    }
    if (['reference', 'reference-light'].includes(process.argv[2])) {
        await call('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
        await call('Page.navigate', {url: process.argv[2] === 'reference-light' ?
            'https://niceadmin-mui-nextjs-main.vercel.app/' : 'https://niceadmin-mui-nextjs-dark.vercel.app/'});
        await until(`document.querySelectorAll('.MuiPaper-root').length > 2`);
        const palette = await evaluate(`({title: document.title, body: getComputedStyle(document.body).backgroundColor,
            papers: Array.from(document.querySelectorAll('.MuiPaper-root')).slice(0,6).map(el => ({background: getComputedStyle(el).backgroundColor, color: getComputedStyle(el).color, radius: getComputedStyle(el).borderRadius})),
            buttons: Array.from(document.querySelectorAll('button')).slice(0,6).map(el => ({background: getComputedStyle(el).backgroundColor, color: getComputedStyle(el).color}))})`);
        const screenshot = await call('Page.captureScreenshot', {format: 'png'});
        await writeFile(`${root}/niceadmin-${process.argv[2]}.png`, Buffer.from(screenshot.data, 'base64'));
        results.push({reference: palette});
        console.log(JSON.stringify(palette));
    }
    if (process.argv[2] === 'responsive') {
        await qaFetch(qaOrigin + '/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'normal', seconds: 3600, delay: 0})});
        await call('Page.navigate', {url: qaOrigin + '/'});
        const lead = `document.querySelector('#approval-trend-chart .js-plotly-plot')`;
        await until(`${lead}?.data?.length === 1 && document.querySelector('#pending-chart .js-plotly-plot')?.data?.length`);
        for (const width of [390, 1024, 1366, 1440, 1920, 2560, 390]) {
            await call('Emulation.setDeviceMetricsOverride', {width, height: 950, deviceScaleFactor: 1, mobile: false});
            await until(`Array.from(document.querySelectorAll('#dashboard-page .chart-surface')).every(g => {
                const p = g.querySelector('.js-plotly-plot');
                return p?._fullLayout && Math.abs(p._fullLayout.width - g.clientWidth) < 3;
            })`);
            const layout = await evaluate(`(() => {
                const plots = Array.from(document.querySelectorAll('#dashboard-page .chart-surface'));
                const charts = plots.map(g => {
                    const p = g.querySelector('.js-plotly-plot'), r = g.getBoundingClientRect();
                    const text = Array.from(p.querySelectorAll('.g-gtitle, .annotation-text, .xtick text, .ytick text'));
                    return {id: g.id, left: r.left, right: r.right,
                        titleClipped: text.some(t => {const b=t.getBoundingClientRect(); return b.width && (b.left < r.left-2 || b.right > r.right+2 || b.top < r.top-2 || b.bottom > r.bottom+2);}),
                        internalOverflow: g.scrollWidth > g.clientWidth + 2};
                });
                return {viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, charts,
                    errors: document.querySelectorAll('.dash-error-card').length,
                    primaryOnly: ${lead}.data.length === 1 && !document.querySelector('#approval-outcomes-chart'),
                    smooth: ${lead}.data[0].line.shape === 'spline',
                    theme: document.querySelector('#main-container').className};
            })()`);
            results.push({mode: 'responsive', width, ...layout});
            if (!layout.primaryOnly || !layout.smooth || layout.charts.some(c => c.internalOverflow))
                throw new Error('Primary metric, spline, or chart bounds regression');
            await evaluate(`window.scrollTo(0,0)`);
            const screenshot = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
            await writeFile(`${root}/responsive-${width}.png`, Buffer.from(screenshot.data, 'base64'));
            console.log(JSON.stringify({width, ...layout}));
        }
        await evaluate(`document.querySelector('#theme-toggle').click()`);
        await until(`document.querySelector('#main-container').className === 'theme-light' && ${lead}.layout.font.color === '#354039'`);
        await evaluate(`document.querySelector('#theme-toggle').click()`);
        await until(`document.querySelector('#main-container').className === 'theme-dark' && ${lead}.layout.font.color === '#ccd0ce'`);
        results.push({themeRoundTrip: true});
    }
    if (process.argv[2] === 'funnel') {
        await qaFetch(qaOrigin + '/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'normal', seconds: 3600, delay: 0})});
        for (const width of [390, 1366]) {
            await call('Emulation.setDeviceMetricsOverride', {width, height: 950, deviceScaleFactor: 1, mobile: false});
            await call('Page.navigate', {url: qaOrigin + '/'});
            const lead = `document.querySelector('#approval-trend-chart .js-plotly-plot')`;
            const rework = `document.querySelector('#rework-ratio-chart .js-plotly-plot')`;
            await until(`${lead}?.data?.length === 1 && ${rework}?.data?.length === 4`);
            const values = await evaluate(`({tiers: ${rework}.data.map(t => t.name),
                hours: ${rework}.data.map(t => t.customdata[0][6]),
                viewport: innerWidth, documentWidth: document.documentElement.scrollWidth})`);
            if (values.tiers[3] !== '3+ Reworks' || values.hours[0] !== '01:00:00' ||
                values.hours[1] !== '00:30:00' || values.documentWidth > width + 2)
                throw new Error('Incorrect rework tier durations or overflowing viewport');
            await evaluate(`document.querySelector('#rework-ratio-chart').scrollIntoView({block:'center',behavior:'instant'})`);
            await new Promise(accept => setTimeout(accept, 300));
            const screenshot = await call('Page.captureScreenshot', {format: 'png'});
            await writeFile(`${root}/funnel-${width}.png`, Buffer.from(screenshot.data, 'base64'));
            await evaluate(`document.querySelector('#theme-toggle').click()`);
            await until(`${lead}.layout.font.color === '#354039'`);
            results.push({width, ...values, themeToggle: true});
        }
    }
    for (const mode of (['local', 'modernization', 'controls', 'rework', 'reference', 'reference-light', 'responsive', 'lifecycle', 'labels', 'latency', 'user-latency', 'daily-latency', 'panel-latency', 'range-filters', 'trend-refresh', 'funnel'].includes(process.argv[2]) ? [] : (process.argv[2] || 'normal,many,empty,one,zero,large,failure').split(','))) {
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode, seconds: 3600, auditor_seconds: 0, admin_seconds: 0, delay: 0})});
        for (const width of (mode === 'normal' || mode === 'many' ? [390, 768, 1366, 1920] : [390])) {
            await call('Emulation.setDeviceMetricsOverride', {width, height: 950, deviceScaleFactor: 1, mobile: false});
            for (const [route, selector] of [['/', '#pending-chart'], ['/reports/daily', '#daily-work-chart'], ['/reports/user', '#user-work-trend']]) {
                await call('Page.navigate', {url: 'http://127.0.0.1:8059' + route});
                await until(`document.querySelector('${selector} .js-plotly-plot')?.data && !Array.from(document.querySelectorAll('[data-dash-is-loading="true"]')).some(${visible})`);
                await new Promise(accept => setTimeout(accept, 500));
                const layout = await evaluate(`(() => {
                    const visible = ${visible};
                    const cards = Array.from(document.querySelectorAll('.chart-frame')).filter(visible);
                    return {documentWidth: document.documentElement.scrollWidth, viewport: innerWidth,
                        charts: cards.map(card => {const rect = card.getBoundingClientRect();
                            const graph = card.querySelector('.dash-graph');
                            const plot = card.querySelector('.js-plotly-plot');
                            const title = plot?.querySelector('.g-gtitle')?.getBoundingClientRect();
                            const surface = plot?.getBoundingClientRect();
                            const totals = Array.from(plot?.querySelectorAll('.annotation-text') || [])
                                .filter(el => /h$/.test(el.textContent)).map(el => {
                                    const box = el.getBoundingClientRect();
                                    return {text: el.textContent, clipped: box.left < surface.left - 1 ||
                                            box.right > surface.right + 1 || box.top < surface.top - 1 || box.bottom > surface.bottom + 1};
                                });
                            return {id: graph.id, left: rect.left, right: rect.right, height: rect.height,
                                    traces: plot?.data?.length || 0, annotations: (plot?.layout?.annotations || []).map(a => a.text),
                                    svgWidth: plot?._fullLayout?.width, svgHeight: plot?._fullLayout?.height,
                                    graphHeight: graph.getBoundingClientRect().height,
                                    titleClipped: !!(title?.height && title.top < surface.top - 1), totals,
                                    legendEntries: Array.from(plot?.querySelectorAll('.legendtext') || []).map(el => el.textContent)};}),
                        errors: document.querySelectorAll('.dash-error-card').length};})()`);
                const label = `${mode}-${width}-${route.replaceAll('/', '_') || 'main'}`;
                const screenshot = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
                await writeFile(`${root}/${label}.png`, Buffer.from(screenshot.data, 'base64'));
                results.push({mode, width, route, ...layout});
                console.log(JSON.stringify({mode, width, route, charts: layout.charts.length,
                    overflow: layout.charts.filter(card => card.left < -1 || card.right > width + 1).map(card => card.id), errors: layout.errors}));
            }
        }
    }
    if (process.argv[2] === 'trend-refresh') {
        for (const width of [390, 1366]) {
            await qaFetch(qaOrigin + '/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({trend_completion: true, trend_delay: 10, trend_failure: false,
                                      trend_saved_seconds: 3600, trend_live_seconds: 7200})});
            await call('Emulation.setDeviceMetricsOverride', {width, height: 950, deviceScaleFactor: 1, mobile: false});
            const began = Date.now();
            await call('Page.navigate', {url: qaOrigin + '/'});
            const completion = `document.querySelector('#approval-trend-chart .js-plotly-plot')?.data?.find(t => t.name.startsWith('Completed video'))`;
            await until(`${completion}?.y.at(-1) === 1 && document.querySelector('#approval-trend-status')?.textContent.includes('Checking latest completion')`);
            const savedPaintMs = Date.now() - began;
            if (savedPaintMs >= 10000) throw new Error('Saved trend waited for live capture');
            await evaluate(`document.querySelector('#theme-toggle').click()`);
            await until(`${completion}?.y.at(-1) === 2`);
            const plot = await evaluate(`(() => {const p = document.querySelector('#approval-trend-chart .js-plotly-plot'); const r = p.getBoundingClientRect(); return {width: r.width, left: r.left, right: r.right, x: p.data.at(-1).x.at(-1), status: document.querySelector('#approval-trend-status').textContent};})()`);
            if (plot.right > width + 1 || plot.left < 0) throw new Error('Trend exceeds viewport');
            results.push({width, savedPaintMs, liveHours: 2, themeDuringCapture: true, plot});
        }
        await qaFetch(qaOrigin + '/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({trend_delay: 1, trend_failure: true})});
        await call('Page.navigate', {url: qaOrigin + '/'});
        await until(`document.querySelector('#approval-trend-status')?.textContent.includes('refresh or persistence could not be verified')`);
        const retainedHours = await evaluate(`document.querySelector('#approval-trend-chart .js-plotly-plot').data.find(t => t.name.startsWith('Completed video')).y.at(-1)`);
        if (retainedHours !== 1) throw new Error('Failed check erased saved completion');
        results.push({failedRefreshRetainedHours: retainedHours});
        console.log(JSON.stringify(results));
    }
    if (process.argv[2] === 'range-filters') {
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'normal', seconds: 3600, rework_delay: 0, dashboard_delay: 0, delay: 0,
                range_sensitive: true, seed_panels: true})});
        await call('Emulation.setDeviceMetricsOverride', {width: 1366, height: 950, deviceScaleFactor: 1, mobile: false});
        await call('Page.navigate', {url: 'http://127.0.0.1:8059/'});
        const hours = `document.querySelector('#individual-chart .js-plotly-plot')?._fullData?.[0]?.y?.[0]`;
        await until(`${hours} === 6`);
        const setDate = async (id, value) => {
            await evaluate(`(() => {const el = document.getElementById(${JSON.stringify(id)});
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, ${JSON.stringify(value)});
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));})()`);
        };
        await setDate('date-from', '2026-10-02');
        await until(`${hours} === 5`);
        const lineDates = `document.querySelector('#approval-trend-chart .js-plotly-plot')?._fullData?.[0]?.x`;
        await until(`${lineDates}?.[0] === '2026-10-02'`);
        await setDate('date-to', '2026-10-05');
        await until(`${hours} === 4`);
        await until(`${lineDates}?.at(-1) === '2026-10-05'`);
        const dropdown = await evaluate(`(() => {const r = document.querySelector('#settlement-dropdown').getBoundingClientRect();
            return {x: r.left + r.width / 2, y: r.top + r.height / 2};})()`);
        await call('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...dropdown});
        await call('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...dropdown});
        await until(`Array.from(document.querySelectorAll('.VirtualizedSelectOption, [role="option"]')).some(el => el.textContent.includes('September 2026'))`);
        const option = await evaluate(`(() => {const el = Array.from(document.querySelectorAll('.VirtualizedSelectOption, [role="option"]')).find(el => el.textContent.includes('September 2026'));
            const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};})()`);
        await call('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...option});
        await call('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...option});
        await until(`document.querySelector('#date-from').value === '2026-09-01' && document.querySelector('#date-to').value === '2026-09-30' && ${hours} === 30`);
        await until(`${lineDates}?.[0] === '2026-09-01' && ${lineDates}?.at(-1) === '2026-09-30'`);
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({dashboard_delay: 0.2})});
        await setDate('date-to', '2026-10-08');
        await setDate('date-from', '2026-10-03');
        await setDate('date-from', '2026-10-04');
        await evaluate(`document.querySelector('#theme-toggle').click()`);
        await until(`${hours} === 5 && document.querySelector('#individual-chart .js-plotly-plot')?.layout.title.text.includes('2026-10-04') && document.querySelector('#individual-chart .js-plotly-plot')?.layout.title.text.includes('2026-10-08')`);
        await until(`${lineDates}?.[0] === '2026-10-04' && ${lineDates}?.at(-1) === '2026-10-08'`);
        results.push({mode: 'range-filters', fromHours: 5, toHours: 4, dropdownHours: 30,
            lineRangeUpdated: true, rapidChangesAndTheme: true});
    }
    if (process.argv[2] === 'panel-latency') {
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'normal', seconds: 3600, rework_delay: 10, dashboard_delay: 0, delay: 0, seed_panels: true})});
        const start = Date.now();
        await call('Page.navigate', {url: 'http://127.0.0.1:8059/'});
        await until(`document.querySelector('#rework-ratio-chart .js-plotly-plot')?.data?.length && document.querySelector('#rework-ratio-chart-status')?.textContent.includes('Checking latest data')`);
        const savedMs = Date.now() - start;
        if (savedMs >= 6000) throw new Error('Saved chart waited for delayed source');
        await until(`document.querySelector('#individual-chart-status')?.textContent.startsWith('Captured ')`);
        const completionMs = Date.now() - start;
        if (completionMs >= 8000 || !await evaluate(`document.querySelector('#rework-ratio-chart-status')?.textContent.includes('Checking latest data')`))
            throw new Error('Completion waited for rework');
        await evaluate(`document.querySelector('#theme-toggle').click()`);
        await until(`document.querySelector('#main-container').className.includes('theme-light')`);
        if (!await evaluate(`document.querySelector('#rework-ratio-chart-status')?.textContent.includes('Checking latest data')`))
            throw new Error('Theme lost saved capture status');
        await until(`document.querySelector('#rework-ratio-chart-status')?.textContent.startsWith('Captured ')`);
        const reworkMs = Date.now() - start;
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'failure', rework_delay: 0})});
        await evaluate(`document.querySelector('#refresh-btn').click()`);
        await until(`document.querySelector('#rework-ratio-chart-status')?.textContent.includes('Latest check failed')`);
        if (!await evaluate(`document.querySelector('#rework-ratio-chart .js-plotly-plot')?.data?.length > 0`))
            throw new Error('Failed check discarded saved chart');
        results.push({mode: 'panel-latency', savedMs, completionMs, reworkMs, failureRetained: true});
    }
    if (process.argv[2] === 'latency') {
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'normal', seconds: 3600, delay: .3, dashboard_delay: 10, workflow_delay: 10})});
        await call('Emulation.setDeviceMetricsOverride', {width: 1366, height: 950, deviceScaleFactor: 1, mobile: false});
        const began = Date.now();
        await call('Page.navigate', {url: 'http://127.0.0.1:8059/'});
        await until(`document.querySelector('#pending-chart .js-plotly-plot')?.data?.length && document.querySelector('#approval-trend-chart .js-plotly-plot')?.data?.length`);
        const loadedMs = Date.now() - began;
        const mainLoading = await evaluate(`document.querySelector('#individual-chart-status').textContent.includes('Checking latest data')`);
        if (loadedMs >= 6000 || !mainLoading) throw new Error('Independent plots waited for the ten-second main/workflow callbacks');
        results.push({initialPlotsMs: loadedMs, mainStillLoading: mainLoading});
        await until(`document.querySelector('#individual-chart-status').textContent.startsWith('Captured ')`);
        await evaluate(`document.querySelector('#refresh-btn').click()`);
        await until(`document.querySelector('#individual-chart-status').textContent.includes('Checking latest data')`);
        await evaluate(`document.querySelector('#universal-legend').scrollIntoView({block: 'center', behavior: 'instant'})`);
        const pointer = await evaluate(`(() => {const r = document.querySelector('#universal-legend .legendtoggle').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};})()`);
        const selectionBegan = Date.now();
        await call('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...pointer});
        await call('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...pointer});
        await until(`document.querySelector('#pending-chart .js-plotly-plot')?.data?.[0]?.x?.length === 1`, 2500);
        results.push({selectionMs: Date.now() - selectionBegan,
            mainStillLoading: await evaluate(`document.querySelector('#individual-chart-status').textContent.includes('Checking latest data')`)});
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({delay: 0, dashboard_delay: 0, workflow_delay: 0})});
        console.log(JSON.stringify(results));
    }
    if (process.argv[2] === 'daily-latency') {
        const scenario = values => fetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)});
        await scenario({mode: 'normal', daily_live_delay: 10, daily_live_failure: false});
        await call('Emulation.setDeviceMetricsOverride', {width: 1366, height: 950, deviceScaleFactor: 1, mobile: false});
        const began = Date.now();
        await call('Page.navigate', {url: 'http://127.0.0.1:8059/reports/daily'});
        await until(`document.querySelectorAll('#daily-report-content .js-plotly-plot').length === 4 && document.querySelector('#daily-work-chart .js-plotly-plot')?.data?.length`);
        const chartsMs = Date.now() - began;
        const pendingText = `document.querySelector('#daily-report-content')?.textContent.includes('checking the latest')`;
        if (chartsMs >= 6000 || !await evaluate(pendingText)) throw new Error('Daily first paint waited for live verification');
        const total = `Array.from(document.querySelector('#daily-work-chart .js-plotly-plot')._fullData).filter(t => t.type === 'bar').reduce((s,t) => s + Array.from(t.y).reduce((a,b) => a + b, 0), 0)`;
        const savedHours = await evaluate(total);
        if (!(savedHours > 0)) throw new Error('Saved daily figures missing');
        await evaluate(`document.querySelector('#theme-toggle').click()`);
        await until(`!!document.querySelector('#theme-toggle .bi-moon-stars-fill')`);
        if (!await evaluate(pendingText)) throw new Error('Theme change lost the pending notice');
        await until(`!(${pendingText})`, 15000);
        const liveHours = await evaluate(total);
        if (liveHours !== savedHours * 2) throw new Error('Fresh daily figures did not replace saved figures');
        results.push({initialChartsMs: chartsMs, savedHours, liveHours, themeDuringLiveCapture: true});
        await scenario({daily_live_delay: .5, daily_live_failure: true});
        await evaluate(`document.querySelector('#refresh-btn').click()`);
        await until(`document.querySelector('#daily-report-content')?.textContent.includes('Latest submissions could not be verified')`);
        if (await evaluate(total) !== savedHours) throw new Error('Failed capture lost recorded figures');
        results.push({failedLiveCaptureRetainsSavedFigures: true});
        await scenario({daily_live_delay: 0, daily_live_failure: false});
        console.log(JSON.stringify(results));
    }
    if (process.argv[2] === 'user-latency') {
        const scenario = values => fetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)});
        await scenario({mode: 'normal', user_report_delay: 10, user_completion_delay: 0});
        await call('Emulation.setDeviceMetricsOverride', {width: 1366, height: 950, deviceScaleFactor: 1, mobile: false});
        const began = Date.now();
        await call('Page.navigate', {url: 'http://127.0.0.1:8059/reports/user'});
        await until(`document.querySelector('#user-report-person')?.textContent.includes('Priya')`);
        const namesMs = Date.now() - began;
        if (namesMs >= 5000 || await evaluate(`!!document.querySelector('#user-work-trend .js-plotly-plot')?.data`))
            throw new Error('Initial roster waited for slow report loading');
        results.push({initialNamesMs: namesMs, reportStillLoading: true});
        await until(`document.querySelector('#user-work-trend .js-plotly-plot')?.data?.length`);
        await scenario({user_report_delay: .2, user_completion_delay: 10});
        await call('Page.navigate', {url: 'about:blank'});
        const chartBegan = Date.now();
        await call('Page.navigate', {url: 'http://127.0.0.1:8059/reports/user'});
        await until(`document.querySelectorAll('#user-report-content .js-plotly-plot').length === 3 && document.querySelector('#user-work-trend .js-plotly-plot')?.data?.length`);
        const chartsMs = Date.now() - chartBegan;
        const completionPending = await evaluate(`document.querySelector('#user-report-completed-card')?.textContent.includes('Loading completion')`);
        if (chartsMs >= 6000 || !completionPending) throw new Error('User charts waited for completion');
        results.push({initialChartsMs: chartsMs, completionStillLoading: completionPending});
        const select = await evaluate(`(() => {const el = document.querySelector('#user-report-person'); const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};})()`);
        await call('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...select});
        await call('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...select});
        await until(`Array.from(document.querySelectorAll('.VirtualizedSelectOption, [role="option"]')).some(el => el.textContent.trim() === 'Riya')`);
        const option = await evaluate(`(() => {const el = Array.from(document.querySelectorAll('.VirtualizedSelectOption, [role="option"]')).find(el => el.textContent.trim() === 'Riya'); const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};})()`);
        const switchBegan = Date.now();
        await call('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...option});
        await call('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...option});
        await until(`document.querySelector('#user-report-content h2')?.textContent === 'Riya'`, 3000);
        results.push({switchPersonMs: Date.now() - switchBegan});
        await evaluate(`document.querySelector('#user-work-trend .js-plotly-plot').dataset.qaRetained = 'yes'`);
        await until(`document.querySelector('#user-report-completed-card')?.textContent.includes('2 completed tasks')`, 15000);
        if (!await evaluate(`document.querySelector('#user-work-trend .js-plotly-plot')?.dataset.qaRetained === 'yes'`))
            throw new Error('Completion update remounted work charts');
        results.push({completionUpdatedWithoutChartRemount: true});
        await scenario({user_report_delay: 0, user_completion_delay: 0});
        console.log(JSON.stringify(results));
    }
    if (process.argv[2] === 'labels') {
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'normal', seconds: 3600, auditor_seconds: 7200, admin_seconds: 1800, delay: 0})});
        for (const width of [390, 1366]) {
            await call('Emulation.setDeviceMetricsOverride', {width, height: 950, deviceScaleFactor: 1, mobile: false});
            await call('Page.navigate', {url: 'http://127.0.0.1:8059/'});
            const p = `document.querySelector('#pending-chart .js-plotly-plot')`;
            await until(`${p}?.layout?.annotations?.some(a => a.name === 'bar-hour-total' && a.text === '3.50h')`);
            const inspect = `(() => {const p = ${p}; return {labels: p.layout.annotations.filter(a => a.name === 'bar-hour-total').map(a => a.text), range: p.layout.yaxis.range};})()`;
            const initial = await evaluate(inspect);
            await evaluate(`(async () => {const p = ${p}; const index = p.data.findIndex(t => t.name === 'Pending Auditor'); await Plotly.restyle(p, {visible: 'legendonly'}, [index]); return true;})()`);
            await until(`${p}.layout.annotations.filter(a => a.name === 'bar-hour-total').every(a => a.text === '1.50h')`);
            const hidden = await evaluate(inspect);
            await evaluate(`(async () => {const p = ${p}; const index = p.data.findIndex(t => t.name === 'Pending Auditor'); await Plotly.restyle(p, {visible: true}, [index]); return true;})()`);
            await until(`${p}.layout.annotations.filter(a => a.name === 'bar-hour-total').every(a => a.text === '3.50h')`);
            if (Math.abs(initial.range[1] - 3.85) > 1e-9 || Math.abs(hidden.range[1] - 1.65) > 1e-9)
                throw new Error('Totals/headroom did not follow visible bar stages');
            results.push({width, initial, hidden, restored: await evaluate(inspect)});
        }
        await qaFetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: 'normal', seconds: 3.6e13, auditor_seconds: 0, admin_seconds: 0, delay: 0})});
        await call('Page.navigate', {url: 'http://127.0.0.1:8059/'});
        const largePlot = `document.querySelector('#pending-chart .js-plotly-plot')`;
        await until(`${largePlot}?.layout?.annotations?.some(a => a.name === 'bar-hour-total' && a.text === '1e+10h')`);
        await evaluate(`(async () => {const p = ${largePlot}; const index = p.data.findIndex(t => t.name === 'Pending Auditor'); await Plotly.restyle(p, {visible: 'legendonly'}, [index]); return true;})()`);
        await until(`${largePlot}.layout.annotations.some(a => a.name === 'bar-hour-total' && a.text === '1e+10h')`);
        results.push({largeAfterLegendChange: await evaluate(`${largePlot}.layout.annotations.filter(a => a.name === 'bar-hour-total').map(a => a.text)`)});
        console.log(JSON.stringify(results));
    }
    if (process.argv[2] === 'lifecycle') {
        await call('Emulation.setDeviceMetricsOverride', {width: 1366, height: 950, deviceScaleFactor: 1, mobile: false});
        const scenario = async values => fetch('http://127.0.0.1:8059/qa/scenario', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)});
        const pendingPlot = `document.querySelector('#pending-chart .js-plotly-plot')`;
        const current = `${pendingPlot}?._fullData?.[0]?.y?.[0]`;
        await scenario({mode: 'normal', seconds: 3600, delay: 0});
        await call('Page.navigate', {url: 'http://127.0.0.1:8059/'});
        await until(`${current} === 1`);
        await evaluate(`document.querySelector('#pending-chart').scrollIntoView({block: 'center', behavior: 'instant'})`);
        await new Promise(accept => setTimeout(accept, 400));
        await scenario({seconds: 1800, delay: 5});
        await evaluate(`document.querySelector('#refresh-btn').click()`);
        await until(`document.querySelector('#pending-chart').getAttribute('data-dash-is-loading') === 'true'`);
        const slow = await evaluate(`({hours: ${current}, pointerEvents: getComputedStyle(document.querySelector('#pending-chart')).pointerEvents, label: getComputedStyle(document.querySelector('#pending-chart').closest('.chart-frame'), '::after').content})`);
        if (slow.hours !== 1 || slow.pointerEvents === 'none') throw new Error('Refresh disabled the previous chart');
        const legendPointer = await evaluate(`(() => {const r = ${pendingPlot}.querySelector('.legendtoggle').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};})()`);
        await call('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...legendPointer});
        await call('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...legendPointer});
        await until(`${pendingPlot}.data[0].visible === 'legendonly'`, 1000);
        results.push({slow, legendInteractiveDuringRefresh: true});
        await until(`${current} === .5 && document.querySelector('#pending-chart').getAttribute('data-dash-is-loading') !== 'true'`);
        await scenario({mode: 'failure', delay: 0});
        await evaluate(`document.querySelector('#refresh-btn').click()`);
        await until(`${pendingPlot}?.data?.length === 0 && ${pendingPlot}?.layout?.annotations?.[0]?.text.includes('unavailable')`);
        results.push({failure: 'unavailable; previous values removed'});
        await scenario({mode: 'normal', seconds: 900});
        await evaluate(`document.querySelector('#refresh-btn').click()`);
        await until(`${current} === .25`);
        await evaluate(`document.querySelector('#nav-daily-report').click()`);
        await until(`location.pathname === '/reports/daily' && document.querySelector('#daily-work-chart .js-plotly-plot')?.data`);
        await scenario({seconds: 60});
        await evaluate(`document.querySelector('#nav-dashboard').click()`);
        await until(`Math.abs(${current} - 1/60) < 1e-9`);
        results.push({navigation: 'fresh values on return'});
        await scenario({seconds: 120});
        await evaluate(`document.querySelector('#workflow-bell').click()`);
        await until(`Math.abs(${current} - 1/30) < 1e-9`);
        results.push({workflow: 'review values refetched after workflow update'});
        await evaluate(`document.querySelector('.modal .btn-close')?.click()`);
        await until(`!Array.from(document.querySelectorAll('.modal, .modal-backdrop')).some(${visible})`);
        await evaluate(`${pendingPlot}.scrollIntoView({block: 'center', behavior: 'instant'})`);
        await new Promise(accept => setTimeout(accept, 400));
        const pointer = await evaluate(`(() => {
            const p = ${pendingPlot};
            const r = p.getBoundingClientRect(), data = p._fullData[0], layout = p._fullLayout;
            return {x: r.left + layout.xaxis._offset + layout.xaxis.d2p(data.x[0]),
                    y: r.top + layout.yaxis._offset + layout.yaxis.d2p(data.y[0] / 2)};
        })()`);
        await call('Input.dispatchMouseEvent', {type: 'mouseMoved', ...pointer});
        await until(`document.querySelector('.chart-tooltip:not([hidden])')`);
        results.push({tooltip: await evaluate(`(() => {const t = document.querySelector('.chart-tooltip'); const r = t.getBoundingClientRect(); return {text: t.textContent, withinViewport: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight};})()`)});
        const hiddenTables = await evaluate(`document.querySelectorAll('.chart-data-access, .chart-frame details, .chart-frame table').length`);
        if (hiddenTables) throw new Error('Chart data tables are still mounted');
        results.push({hiddenTables});
        // Dense horizontal bars must remain fully visible and let vertical wheel
        // input scroll the page even when the pointer is over the plot itself.
        await scenario({mode: 'many', seconds: 3600, delay: 0});
        await evaluate(`document.querySelector('#refresh-btn').click()`);
        await until(`new Set((document.querySelector('#assigned-chart .js-plotly-plot')?.data || []).filter(t => t.type === 'bar').flatMap(t => t.y || [])).size === 35`);
        await new Promise(accept => setTimeout(accept, 400));
        await evaluate(`document.querySelector('#assigned-chart').scrollIntoView({block: 'start', behavior: 'instant'})`);
        const dense = await evaluate(`(() => {
            const graph = document.querySelector('#assigned-chart'), viewport = graph.closest('.chart-viewport');
            const r = graph.getBoundingClientRect();
            return {graphHeight: r.height, viewportHeight: viewport.clientHeight, scrollY,
                    x: r.left + r.width / 2, y: Math.min(innerHeight - 100, Math.max(100, r.top + 180))};
        })()`);
        if (dense.graphHeight <= 660 || dense.viewportHeight < dense.graphHeight - 1)
            throw new Error('Dense plot has a vertical scroll trap');
        await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x: dense.x, y: dense.y, deltaX: 0, deltaY: 350});
        await until(`scrollY > ${dense.scrollY + 100}`);
        const down = await evaluate('scrollY');
        await call('Input.dispatchMouseEvent', {type: 'mouseWheel', x: dense.x, y: dense.y, deltaX: 0, deltaY: -350});
        await until(`scrollY < ${down - 100}`);
        results.push({dense, wheelScrollDown: down, wheelScrollUp: await evaluate('scrollY')});
        console.log(JSON.stringify(results));
    }
    const reportName = process.argv[2] === 'lifecycle' ? 'lifecycle' : process.argv[2] ? `audit-${process.argv[2].replaceAll(',', '-')}` : 'audit';
    await writeFile(`${root}/${reportName}.json`, JSON.stringify({results, errors}, null, 2));
    const failedLayouts = results.filter(row => row.charts && (row.errors || row.documentWidth > row.viewport + 1 ||
        row.charts.some(chart => chart.left < -1 || chart.right > row.width + 1 || chart.titleClipped ||
                                 chart.totals?.some(label => label.clipped))));
    if (errors.length || failedLayouts.length) throw new Error(`Browser audit failed: ${errors.length} runtime/network errors; ${failedLayouts.length} invalid layouts`);
} catch (error) {
    const status = await evaluate(`Array.from(document.querySelectorAll('[id$="-status"]')).map(el => ({id: el.id, text: el.textContent}))`).catch(() => []);
    const chart = await evaluate(`(() => {const p = document.querySelector('#individual-chart .js-plotly-plot'); return {from: document.querySelector('#date-from')?.value, to: document.querySelector('#date-to')?.value, data: p?.data, fullX: Array.from(p?._fullData?.[0]?.x || [])};})()`).catch(() => null);
    await writeFile(`${root}/audit-failure.json`, JSON.stringify({message: error.message, status, chart, callbackRequests, errors}, null, 2));
    throw error;
} finally {
    await send('Browser.close').catch(() => {});
    ws.close();
    chrome.kill();
}

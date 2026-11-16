"""Exercise the real local runner without loading credentials or dashboard data."""
import ast
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def test_python_changes_restart_server_and_css_updates_browser_hash(tmp_path):
    # Extract the actual runner so this subprocess cannot initialize DataManager.
    application = Path(__file__).parents[1] / 'src/slicing_dashboard/app.py'
    runner = next(node for node in ast.parse(application.read_text(encoding='utf-8')).body
                  if isinstance(node, ast.FunctionDef) and node.name == 'run_local')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    dependency = tmp_path / 'reload_value.py'
    dependency.write_text("VALUE = 'original'\n", encoding='utf-8')
    assets = tmp_path / 'assets'
    assets.mkdir()
    stylesheet = assets / 'style.css'
    stylesheet.write_text('body { color: black; }', encoding='utf-8')
    source = tmp_path / 'reload_app.py'
    template = """import os
from dash import Dash, html
from reload_value import VALUE
app = Dash(__name__)
app.layout = html.Div(VALUE + {suffix!r})
@app.server.get('/probe')
def probe():
    return {{'pid': os.getpid(), 'hot_reload': app._dev_tools.hot_reload}}
{runner}
if __name__ == '__main__':
    run_local(port={port})
"""

    def write_app(suffix):
        source.write_text(template.format(suffix=suffix, runner=ast.unparse(runner), port=port),
                          encoding='utf-8')

    def get(path):
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=.5) as response:
            return json.load(response)

    def wait_for(check):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                result = check()
                if result:
                    return result
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(.15)
        raise AssertionError(f'Reload timed out:\n{log.read_text(encoding="utf-8", errors="replace")}')

    def version(label):
        wait_for(lambda: get('/_dash-layout')['props']['children'] == label)
        # Let the stat watcher establish its initial file timestamps.
        time.sleep(1.1)
        assert get('/probe')['hot_reload'] is True
        return get('/probe')['pid'], get('/_reload-hash')['reloadHash']

    write_app('')
    log = tmp_path / 'server.log'
    environment = dict(os.environ)
    for key in ('WERKZEUG_RUN_MAIN', 'WERKZEUG_SERVER_FD'):
        environment.pop(key, None)
    options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
               if os.name == 'nt' else {'start_new_session': True})
    with log.open('w', encoding='utf-8') as output:
        process = subprocess.Popen([sys.executable, '-u', str(source)], cwd=tmp_path,
                                   env=environment, stdout=output, stderr=output, **options)
        try:
            observations = [version('original')]
            dependency.write_text("VALUE = 'changed module'\n", encoding='utf-8')
            observations.append(version('changed module'))
            write_app(' and app')
            observations.append(version('changed module and app'))
            assert len({pid for pid, _ in observations}) == 3
            assert len({marker for _, marker in observations}) == 3

            # A CSS save changes the browser marker without restarting Python.
            stylesheet.write_text('body { color: rebeccapurple; }', encoding='utf-8')

            def changed_hash():
                result = get('/_reload-hash')
                return result if result['reloadHash'] != observations[-1][1] else None

            changed = wait_for(changed_hash)
            assert any(asset['is_css'] and asset['url'].endswith('/style.css') for asset in changed['files'])
            assert get('/probe')['pid'] == observations[-1][0]
            assert '10038' not in log.read_text(encoding='utf-8', errors='replace')
        finally:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)

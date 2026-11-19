"""The installed extension starts the bridge in an interactive Blender with user preferences."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cavi_blender_mcp.bridge_contract import runtime_report
from cavi_blender_mcp.client import BridgeClient


def cli(env, *args):
    return subprocess.run([sys.executable, '-m', 'cavi_blender_mcp.server', *args], env=env,
        check=False, capture_output=True, text=True, timeout=180)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blender', default=shutil.which('blender'), required=not shutil.which('blender'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        env = {**os.environ, 'BLENDER_USER_RESOURCES': str(root/'user'), 'CAVI_BLENDER_BIN': args.blender,
               'CAVI_BLENDER_WORKSPACE': str(root/'workspace'),
               'CAVI_BLENDER_CONNECTION': str(root/'connection.json')}
        env.pop('PYTHONPATH', None)
        installed = cli(env, 'extension', 'install')
        assert installed.returncode == 0, installed.stdout + installed.stderr
        assert not (root/'connection.json').exists(), 'the install process must not start a bridge'
        with (root/'blender.log').open('w') as log:
            process = subprocess.Popen([args.blender, '--no-window-focus',
                '--window-geometry', '0', '0', '640', '480'],
                env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                client, deadline = BridgeClient(root/'connection.json'), time.monotonic()+120
                while True:
                    try:
                        scene = client.call('scene_info', {'limit': 1}, timeout=5)
                        break
                    except ConnectionError:
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError((root/'blender.log').read_text()) from None
                        time.sleep(.2)
                report = runtime_report(client)
                assert report['bridge_compatibility']['matches'], report
                assert not report['background'] and report['pid'] == process.pid, report
                started = cli(env, 'runtime', 'start')
                assert started.returncode == 0, started.stdout + started.stderr
                attached = json.loads(started.stdout)
                assert attached['connected'] and not attached['launch_requested'], attached
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        print(json.dumps({'workspace': scene['workspace'] == str(root/'workspace'),
                          'bridge_matches': True, 'attached_pid': report['pid']}))


if __name__ == '__main__':
    main()

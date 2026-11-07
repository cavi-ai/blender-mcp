"""Bounded subprocess transport for a private native UV computation."""
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from . import process_launch


def solve(executable, workspace, request):
    try:
        return _solve(executable, workspace, request)
    except (OSError, RuntimeError) as exc:
        raise ValueError('Native UV worker could not run; source UVs were not changed: '+str(exc)) from exc


def _solve(executable, workspace, request):
    payload = json.dumps(request).encode()
    if len(payload) > 16*1024*1024:
        raise ValueError('Selected geometry exceeds the 16 MiB UV worker input budget')
    env = dict(os.environ, PYTHONNOUSERSITE='1')
    env.pop('PYTHONPATH', None)
    env.pop('CAVI_BLENDER_CONNECTION', None)
    with tempfile.TemporaryDirectory(prefix='.cavi-uv-', dir=workspace) as folder:
        root = Path(folder)
        input_path, output_path, log_path = root/'input.json', root/'output.json', root/'worker.log'
        input_path.write_bytes(payload)
        with log_path.open('w') as log:
            try:
                command = [executable, '--background', '--factory-startup',
                    '--disable-autoexec', '--python-exit-code', '1', '--python',
                    str(Path(__file__).with_name('blender_uv_region_worker.py')), '--',
                    str(input_path), str(output_path)]
                result = subprocess.run(process_launch.command(command, env=env), env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, timeout=45, start_new_session=True, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('Native UV worker exceeded 45 seconds; source UVs were not changed') from exc
        if result.returncode != 0 or not output_path.is_file():
            raise ValueError('Native UV solving failed; source UVs were not changed: '+log_path.read_text()[-1500:])
        if output_path.stat().st_size > 8*1024*1024:
            raise ValueError('Native UV worker output exceeds 8 MiB')
        output = json.loads(output_path.read_bytes())
        if output.get('input_sha256') != hashlib.sha256(payload).hexdigest():
            raise ValueError('UV worker output is not bound to the selected geometry')
        return output

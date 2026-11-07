"""Use MCP Core's owned-exec client from host Python and the embedded bridge."""

import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
import time
import types
from pathlib import Path

OWNER = 'CAVI_MCP_PROCESS_OWNER'
GATE = 'CAVI_MCP_PROCESS_GATE'


def _active(env):
    parent, child = os.environ.get(OWNER), env.get(OWNER)
    if parent and child != parent:
        raise RuntimeError('A child cannot drop or replace its configured process owner')
    return bool(child)


def _source(path):
    path = Path(path)
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise ValueError('The process gate must use a canonical library path')
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise ValueError('The process gate must be a bounded library file')
        raw = stream.read(65537)
        after = os.fstat(stream.fileno())
    if (len(raw) > 65536 or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) !=
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError('The process gate changed while reading')
    return raw


def _client(env):
    try:
        if Path(sys.executable).name.lower().startswith(('python', 'pypy')):
            core = importlib.import_module('cavi_mcp_core.owned_exec')
            path = Path(core.__file__).resolve(strict=True)
            frame = {'version':1, 'module':str(path),
                     'sha256':hashlib.sha256(_source(path)).hexdigest(),
                     'python':str(Path(sys.executable).resolve(strict=True))}
            if GATE in env and json.loads(env[GATE]) != frame:
                raise ValueError('The process gate handoff differs from installed MCP Core')
        else:
            if GATE not in env:
                raise ValueError('Embedded hosts require the runtime process gate handoff')
            frame = json.loads(env[GATE])
        if (not isinstance(frame, dict) or set(frame) != {'version','module','sha256','python'}
                or type(frame['version']) is not int or frame['version'] != 1
                or any(not isinstance(frame[k], str) for k in ('module','sha256','python'))):
            raise ValueError('Invalid runtime process gate handoff')
        python = Path(frame['python'])
        if (not python.is_absolute() or python != python.resolve(strict=True)
                or not python.is_file() or not os.access(python, os.X_OK)
                or not python.name.lower().startswith(('python', 'pypy'))):
            raise ValueError('The process gate requires its trusted host Python interpreter')
        source = _source(frame['module'])
        if hashlib.sha256(source).hexdigest() != frame['sha256']:
            raise ValueError('The runtime process gate library changed')
        # Load only this stdlib module, not the host's site-packages or ABI extensions.
        module = types.ModuleType('cavi_blender_mcp._owned_exec')
        module.__file__ = frame['module']
        exec(compile(source, frame['module'], 'exec'), module.__dict__)  # noqa: S102 - load the hash-bound stdlib dependency without host ABI imports
        if not callable(getattr(module, 'command', None)):
            raise TypeError('The process gate command API is unavailable')
        return module, frame
    except (ImportError, OSError, ValueError, TypeError, SyntaxError, AttributeError) as error:
        raise RuntimeError('MCP Core owned-exec gate is unavailable or changed: '+str(error)) from error


def environment(env):
    """Seal the pure gate and host interpreter for Blender's separate Python ABI."""
    result = dict(env)
    if _active(result):
        _module, frame = _client(result)
        result[GATE] = json.dumps(frame, sort_keys=True)
    return result


def command(args, *, env, cwd=None, launch_id=None):
    if not _active(env):
        return list(map(str, args))
    module, frame = _client(env)
    try:
        return module.command(args, cwd=cwd, env=env, python=frame['python'],launch_id=launch_id)
    except (OSError, ValueError, TypeError) as error:
        raise RuntimeError('Process launch registration failed: '+str(error)) from error


def wait_registered(process, *, env, launch_id, args, timeout=5):
    """Keep a short-lived launcher alive until the owner has recorded its child."""
    try:
        module, _frame = _client(env)
        owner, _digest = module.configuration(env[OWNER])
        deadline = time.monotonic()+min(timeout,5)
        while True:
            if process.poll() is not None:
                raise RuntimeError('The child exited before registration was observed')
            records = list(Path(owner['records']).glob('*.json'))
            if len(records)>1024:
                raise ValueError('The owner registration directory exceeds its launch limit')
            for path in records:
                try:
                    record = module.parse(module.read_private(path))
                except (OSError,ValueError):
                    continue  # A record can be visible before its writer finishes.
                request = record.get('request') if isinstance(record,dict) else None
                if (isinstance(request,dict) and request.get('launch_id')==launch_id
                        and request.get('pid')==process.pid and request.get('pgid')==process.pid
                        and request.get('parent_pid')==os.getpid()
                        and request.get('attempt')==owner['attempt'] and request.get('command')==args
                        and request.get('cwd')==os.getcwd()
                        and request.get('environment_sha256')==module.digest(env)
                        and isinstance(record.get('birth_identity'),str) and record['birth_identity']):
                    return
            if time.monotonic()>=deadline:
                raise TimeoutError('The owner did not record this launch before its deadline')
            time.sleep(.01)
    except BaseException as error:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        raise RuntimeError('Blender launch registration was not observed: '+str(error)) from error

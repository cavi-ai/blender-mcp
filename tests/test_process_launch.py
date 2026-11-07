"""Owned launch adoption; native subprocess boundaries are always blocked."""
import hashlib
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import generation, runtime, uv_worker

OWNER = 'CAVI_MCP_PROCESS_OWNER'
FRAME = 'CAVI_MCP_PROCESS_GATE'


@contextmanager
def backend(root, source=None):
    file = root / 'owned_exec.py'
    file.write_text(source or 'def command(args, **kwargs):\n    raise RuntimeError("registration refused")\n')
    module = types.ModuleType('cavi_mcp_core.owned_exec')
    module.__file__ = str(file)
    frame = {'version':1, 'module':str(file),
             'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
             'python':str(Path(sys.executable).resolve())}
    with patch.dict(sys.modules, {'cavi_mcp_core.owned_exec':module}):
        yield frame


def offline(*_args):
    raise ConnectionError('offline') from FileNotFoundError('connection')


class OwnedLaunchTests(unittest.TestCase):
    def registration_backend(self, root):
        return SimpleNamespace(configuration=lambda path:({'records':str(root),'attempt':'attempt'},'hash'),
            parse=json.loads,read_private=lambda path:path.read_bytes(),digest=lambda env:'environment')

    def registration(self, launch_id):
        return {'birth_identity':'birth','request':{'pid':123,'pgid':123,'parent_pid':os.getpid(),
            'launch_id':launch_id,'attempt':'attempt','command':['native'],
            'cwd':os.getcwd(),'environment_sha256':'environment'}}

    def test_registration_wait_requires_the_matching_child_and_launch(self):
        launch = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'other.json').write_text(json.dumps(self.registration('different-launch')))
            observed = []
            child = SimpleNamespace(pid=123,poll=lambda:None,
                terminate=lambda:observed.append('terminated'),wait=lambda **kwargs:None)
            timer = threading.Timer(.03,lambda:(root/'matching.json').write_text(json.dumps(self.registration('launch'))))
            timer.start()
            try:
                with patch.object(launch,'_client',return_value=(self.registration_backend(root),{})):
                    launch.wait_registered(child,env={OWNER:'owner'},launch_id='launch',args=['native'],timeout=.5)
                self.assertTrue((root/'matching.json').exists())
                self.assertEqual(observed,[])
            finally:
                timer.join()

    def test_unobserved_registration_retires_the_child_and_reports_failure(self):
        launch = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'other.json').write_text(json.dumps(self.registration('different-launch')))
            observed = []
            child = SimpleNamespace(pid=123,poll=lambda:None,
                terminate=lambda:observed.append('terminated'),wait=lambda **kwargs:observed.append('waited'))
            with patch.object(launch,'_client',return_value=(self.registration_backend(root),{})), \
                    self.assertRaisesRegex(RuntimeError,'deadline'):
                launch.wait_registered(child,env={OWNER:'owner'},launch_id='launch',args=['native'],timeout=.01)
            self.assertEqual(observed,['terminated','waited'])

    def module(self):
        try:
            return importlib.import_module('cavi_blender_mcp.process_launch')
        except ImportError:
            self.fail('Native helpers must use the shared owned-exec gate')

    def test_reconstruction_refusal_stops_before_the_worker_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with backend(root), patch.dict(os.environ, {OWNER:str(root/'owner.json')}), \
                    patch.object(generation.subprocess, 'run', side_effect=AssertionError('ungated worker')), \
                    self.assertRaisesRegex(RuntimeError, 'registration refused'):
                generation.run([sys.executable, '-c', 'raise SystemExit(0)'], dict(os.environ),
                               10, time.monotonic()+10)

    def test_runtime_refusal_stops_before_blender_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            binary = root/'blender'
            binary.write_bytes(b'not an application')
            binary.chmod(0o700)
            with backend(root), patch.dict(os.environ, {
                    OWNER:str(root/'owner.json'), 'CAVI_BLENDER_BIN':str(binary),
                    'CAVI_BLENDER_WORKSPACE':str(root),
                    'CAVI_BLENDER_CONNECTION':str(root/'connection.json')}), \
                    patch.object(runtime.BridgeClient, 'call', side_effect=offline), \
                    patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('ungated Blender')), \
                    self.assertRaisesRegex(RuntimeError, 'registration refused'):
                runtime.start_runtime(background=True)

    def test_nested_uv_refusal_stops_before_the_blender_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with backend(root) as frame, patch.dict(os.environ, {
                    OWNER:str(root/'owner.json'), FRAME:json.dumps(frame)}), \
                    patch.object(uv_worker.subprocess, 'run', side_effect=AssertionError('ungated UV')), \
                    self.assertRaisesRegex(ValueError, 'registration refused'):
                uv_worker.solve('blender', root, {'vertices':[]})

    def test_owned_runtime_does_not_adopt_a_connected_bridge(self):
        with patch.dict(os.environ, {OWNER:'/private/owner.json'}), \
                patch.object(runtime.BridgeClient, 'call', return_value={'file':'', 'objects':[]}), \
                patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('unexpected launch')), \
                self.assertRaisesRegex(RuntimeError, 'connected'):
            runtime.start_runtime(background=True)

    def test_owned_runtime_requires_background_mode(self):
        with patch.dict(os.environ, {OWNER:'/private/owner.json'}), \
                patch.object(runtime.BridgeClient, 'call', return_value={'file':'', 'objects':[]}), \
                patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('unexpected launch')), \
                self.assertRaisesRegex(RuntimeError, 'background'):
            runtime.start_runtime()

    def test_missing_core_capability_refuses_instead_of_falling_back(self):
        launch = self.module()
        with patch.dict(os.environ, {OWNER:'/private/owner.json'}), \
                patch.dict(sys.modules, {'cavi_mcp_core.owned_exec':None}), \
                self.assertRaisesRegex(RuntimeError, 'MCP Core'):
            launch.command(['worker'], env=dict(os.environ))

    def test_child_environment_cannot_drop_the_owner(self):
        launch = self.module()
        with patch.dict(os.environ, {OWNER:'/private/owner.json'}), \
                self.assertRaisesRegex(RuntimeError, 'owner'):
            launch.command(['worker'], env={})

    def test_changed_embedded_gate_is_refused_before_loading_its_code(self):
        launch = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            marker = root/'executed'
            with backend(root, f'from pathlib import Path\nPath({str(marker)!r}).touch()\n') as frame:
                frame['sha256'] = '0'*64
                with patch.dict(os.environ, {OWNER:str(root/'owner.json'), FRAME:json.dumps(frame)}), \
                        self.assertRaisesRegex(RuntimeError, 'gate'):
                    launch.command(['worker'], env=dict(os.environ))
            self.assertFalse(marker.exists())

    def test_runtime_passes_the_registered_command_and_embedded_handoff(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            binary = root/'blender'
            binary.write_bytes(b'not an application')
            binary.chmod(0o700)
            def spawned(command, **kwargs):
                self.assertEqual(command[:3], ['registered',str(binary),'--background'])
                frame = json.loads(kwargs['env'][FRAME])
                self.assertEqual(frame['sha256'], hashlib.sha256((root/'owned_exec.py').read_bytes()).hexdigest())
                self.assertEqual(kwargs['env'][OWNER], str(root/'owner.json'))
                return SimpleNamespace(pid=123)
            with backend(root, 'def command(args, **kwargs): return ["registered", *args]'), \
                    patch.object(runtime.process_launch,'wait_registered'), \
                    patch.dict(os.environ, {OWNER:str(root/'owner.json'),
                        'CAVI_BLENDER_BIN':str(binary), 'CAVI_BLENDER_WORKSPACE':str(root),
                        'CAVI_BLENDER_CONNECTION':str(root/'connection.json')}), \
                    patch.object(runtime.BridgeClient, 'call', side_effect=offline), \
                    patch.object(runtime.subprocess, 'Popen', side_effect=spawned):
                self.assertEqual(runtime.start_runtime(background=True)['pid'], 123)

    def test_runtime_keeps_launcher_alive_until_registration_is_observed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            binary = root/'blender'
            binary.write_bytes(b'not an application'); binary.chmod(0o700)
            observed = []
            with backend(root, 'def command(args, **kwargs): return args'), \
                    patch.dict(os.environ,{OWNER:str(root/'owner.json'),'CAVI_BLENDER_BIN':str(binary),
                        'CAVI_BLENDER_WORKSPACE':str(root),'CAVI_BLENDER_CONNECTION':str(root/'connection.json')}), \
                    patch.object(runtime.BridgeClient,'call',side_effect=offline), \
                    patch.object(runtime.subprocess,'Popen',return_value=SimpleNamespace(pid=123)), \
                    patch.object(runtime.process_launch,'wait_registered',
                        side_effect=lambda *args,**kwargs:observed.append(args[0].pid)):
                runtime.start_runtime(background=True)
            self.assertEqual(observed,[123])

    def test_reconstruction_passes_the_registered_command_to_its_runner(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            def spawned(command, **kwargs):
                self.assertEqual(command, ['registered','worker','input'])
                self.assertEqual(kwargs['env'][OWNER], str(root/'owner.json'))
                return SimpleNamespace(returncode=0, stdout='{}', stderr='')
            with backend(root, 'def command(args, **kwargs): return ["registered", *args]'), \
                    patch.dict(os.environ, {OWNER:str(root/'owner.json')}), \
                    patch.object(generation.subprocess, 'run', side_effect=spawned):
                result = generation.run(['worker','input'], dict(os.environ), 10, time.monotonic()+10)
                self.assertEqual(result.returncode, 0)

    def test_embedded_uv_uses_the_host_gate_without_importing_host_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with backend(root, 'def command(args, **kwargs): return ["registered", *args]') as frame:
                def spawned(command, **kwargs):
                    self.assertEqual(command[:2], ['registered','native-blender'])
                    self.assertNotIn('PYTHONPATH', kwargs['env'])
                    payload = Path(command[-2]).read_bytes()
                    Path(command[-1]).write_text(json.dumps({
                        'input_sha256':hashlib.sha256(payload).hexdigest(), 'uv':[]}))
                    return SimpleNamespace(returncode=0)
                before = list(sys.path)
                with patch.dict(os.environ, {OWNER:str(root/'owner.json'),FRAME:json.dumps(frame)}), \
                        patch.object(sys, 'executable', '/native/Blender'), \
                        patch.dict(sys.modules, {'cavi_mcp_core.owned_exec':None}), \
                        patch.object(uv_worker.subprocess, 'run', side_effect=spawned):
                    self.assertEqual(uv_worker.solve('native-blender', root, {'vertices':[]})['uv'], [])
                self.assertEqual(sys.path, before)

    def test_embedded_launch_without_a_runtime_handoff_refuses(self):
        launch = self.module()
        with patch.dict(os.environ, {OWNER:'/private/owner.json'}, clear=True), \
                patch.object(sys, 'executable', '/native/Blender'), \
                self.assertRaisesRegex(RuntimeError, 'handoff'):
            launch.command(['native-blender'], env=dict(os.environ))

    def test_expired_reconstruction_budget_after_gate_preparation_never_launches(self):
        clock = [9.0]
        def prepared(command, **kwargs):
            clock[0] = 11.0
            return ['registered', *command]
        with patch.object(generation.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(generation.process_launch, 'command', side_effect=prepared), \
                patch.object(generation.subprocess, 'run', side_effect=AssertionError('expired worker launched')), \
                self.assertRaisesRegex(RuntimeError, 'exceeded'):
            generation.run(['worker'], dict(os.environ), 10, 10.0)

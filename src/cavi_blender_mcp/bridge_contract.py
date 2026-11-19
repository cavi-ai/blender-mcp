"""Identify the Blender-side implementation separately from the installed MCP server."""
import hashlib
from pathlib import Path

from cavi_mcp_core import files as core_files
from cavi_mcp_core import workspace as core_workspace

PROTOCOL = 1


def expected_bridge():
    root = Path(__file__).parent
    files = sorted({Path(core_workspace.__file__), Path(core_files.__file__),
                    *root.glob('blender_*.py'), *root.glob('preview_*.py'), root/'operations.py', root/'lease.py',
                    root/'geometry.py', root/'paths.py', root/'importing.py', root/'presets.py',
                    root/'source_identity.py', root/'skin_projection.py', root/'mesh_regions.py',
                    root/'uv_regions.py', root/'uv_worker.py', root/'uv_layout.py', root/'process_launch.py',
                    root/'uv_density.py', root/'mapping.py', root/'vertex_edit.py', root/'surface_ray.py',
                    root/'modifier_settings.py',root/'shader_links.py',root/'native_controls.py',
                    root/'textures.py'})
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return {'protocol': PROTOCOL, 'build': digest.hexdigest()}


def compatibility(actual):
    expected = expected_bridge()
    matches = (isinstance(actual, dict) and actual.get('protocol') == expected['protocol']
               and actual.get('build') == expected['build'])
    return {'matches': matches, 'expected': expected, 'actual': actual,
            'next_action': None if matches else 'preserve_project_and_refresh_bridge'}


def runtime_report(client, restart=False, lease_id=None):
    restarted = client.call('runtime_restart', {'lease_id': lease_id}) if restart else None
    result = client.call('runtime_status', {})
    result['bridge_compatibility'] = compatibility(result.get('bridge'))
    if restarted and result['generation'] != restarted['generation']:
        raise RuntimeError('Bridge changed again after restart; inspect runtime status')
    if restarted:
        result['restarted'] = True
    return result

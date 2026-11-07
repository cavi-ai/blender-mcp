"""Identify the Blender-side implementation separately from the installed MCP server."""
import hashlib
from pathlib import Path

PROTOCOL = 1


def expected_bridge():
    root = Path(__file__).parent
    files = sorted({*root.glob('blender_*.py'), *root.glob('preview_*.py'), root/'operations.py', root/'lease.py',
                    root/'geometry.py', root/'paths.py', root/'importing.py', root/'presets.py',
                    root/'source_identity.py', root/'skin_projection.py', root/'mesh_regions.py',
                    root/'uv_regions.py', root/'uv_worker.py', root/'uv_layout.py',
                    root/'uv_density.py', root/'mapping.py', root/'vertex_edit.py', root/'surface_ray.py',
                    root/'modifier_settings.py',root/'shader_links.py'})
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

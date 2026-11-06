"""Load a saved project without discarding unsaved edits or loading its UI layout."""
import re
from pathlib import Path

from .blender_errors import preflight
from .source_identity import LoadedSource


def snapshot(path):
    source = LoadedSource()
    source.capture(path)
    if source.source is None:
        raise ValueError('Could not identify stable saved project bytes')
    return source.source


def open_project(p, workspace, loaded_source, identity):
    import bpy

    with preflight():
        if set(p) - {'path', 'expected_sha256'}:
            raise ValueError('Open accepts only path and expected_sha256')
        raw = p.get('path')
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError('Open requires an existing workspace .blend path')
        root = Path(workspace).resolve()
        try:
            target = (root / raw).resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ValueError('Open requires an existing workspace .blend file') from exc
        if not target.is_relative_to(root) or target.suffix.lower() != '.blend' or not target.is_file():
            raise ValueError('Open requires an existing workspace .blend file')
        expected = p.get('expected_sha256')
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('expected_sha256 must be a lowercase SHA-256')
        pinned = snapshot(target)
        if expected is not None and expected != pinned['sha256']:
            raise ValueError('Target project does not match expected_sha256')
        current = loaded_source.inspect(bpy.data.filepath, bpy.data.is_dirty)
        if current['dirty']:
            raise ValueError('Unsaved edits must be saved to a new .blend before opening another project')
        if bpy.data.filepath:
            if current['saved_source'] is None:
                raise ValueError('Current saved project identity is unavailable; save to a new .blend first')
            if snapshot(bpy.data.filepath) != current['saved_source']:
                raise ValueError('Current saved project changed on disk; save to a new .blend first')
        same = bpy.data.filepath and str(Path(bpy.data.filepath).resolve()) == str(target)
    if same:
        return {**pinned, 'project_id': identity(), 'opened': False}

    # From this point any failure has an uncertain outcome: loading may have changed data.
    result = bpy.ops.wm.open_mainfile(filepath=str(target), load_ui=False, use_scripts=False)
    if 'FINISHED' not in result:
        raise RuntimeError('Project load did not finish; inspect the session before continuing')
    state = loaded_source.inspect(bpy.data.filepath, bpy.data.is_dirty)
    if state['saved_source'] != pinned or snapshot(target) != pinned or state['dirty']:
        raise RuntimeError('Loaded project identity changed; inspect the session before continuing')
    return {**pinned, 'project_id': identity(), 'opened': True}

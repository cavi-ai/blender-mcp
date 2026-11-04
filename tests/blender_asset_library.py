"""Native append preserves project context and cleans every created ID on failure."""

import hashlib
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp.blender_asset_library import ids

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('asset_library_fixture.py')))
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'baseline.blend'))
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'native-library-context',
        'expected_project': state['project_id']})['lease_id']

    def edit(**params):
        return bridge.dispatch('owned_edit', {'operation': 'append_asset_library',
            'params': {**params, 'lease_id': lease}})

    def inspect(path, kind='collections'):
        return bridge.dispatch('inspect_asset_library', {'path': path, 'kind': kind})

    before = ids()
    source = inspect('kit.blend')
    assert before == ids()
    assert not bpy.data.is_dirty
    assert inspect('kit.blend', 'objects')['names'] == ['Fence', 'LibraryRig', 'LibrarySkin']
    old_file, old_scene, old_selected, old_active = bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    old_handlers = list(bpy.app.handlers.blend_import_post)
    for params in [{'path': 'kit.blend', 'names': ['EditableKit'], 'expected_sha256': '0'*64},
                   {'path': 'kit.blend', 'names': ['Missing'], 'expected_sha256': source['sha256']},
                   {'path': 'kit.blend', 'names': ['EditableKit', 'EditableKit'], 'expected_sha256': source['sha256']},
                   {'path': 'broken.blend', 'kind': 'materials', 'names': ['BrokenFinish'],
                    'expected_sha256': inspect('broken.blend', 'materials')['sha256']}]:
        try:
            edit(**params)
        except (ValueError, RuntimeError):
            pass
        else:
            raise AssertionError('Invalid append succeeded')
        assert before == ids()
        assert list(bpy.app.handlers.blend_import_post) == old_handlers
    result = edit(path='kit.blend', names=['EditableKit'], expected_sha256=source['sha256'])
    assert bpy.data.filepath == old_file and bpy.context.scene == old_scene
    assert set(bpy.context.selected_objects) == old_selected and bpy.context.view_layer.objects.active == old_active
    assert bpy.context.scene.frame_current+bpy.context.scene.frame_subframe == 12.5
    expected = json.loads((root/'expected.json').read_text())
    assert result['images'][0]['sha256'] == expected['packed_sha256']
    imported_collection = bpy.data.collections[result['roots'][0]['name']]
    assert len(imported_collection.all_objects) == 3
    consumer = root/'consumer.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(consumer))
    bpy.ops.wm.open_mainfile(filepath=str(consumer))
    assert bpy.data.objects['Fence'].modifiers[:] == []
    image = next(i for i in bpy.data.images if i.name.startswith('PackedPaint'))
    assert hashlib.sha256(image.packed_file.data).hexdigest() == expected['packed_sha256']
    assert inspect('kit.blend')['sha256'] == source['sha256']
    print(json.dumps({'blender': bpy.app.version_string, 'failed_append_removed_all_new_ids': True,
                      'project_context_preserved': True, 'consumer_reopened': True,
                      'packed_texture_bytes_preserved': True}))

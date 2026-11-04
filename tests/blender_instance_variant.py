"""Native fork dependency remapping, exact texture retention and atomic failure cleanup."""

import hashlib
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_instance_variants as variants
from cavi_blender_mcp.blender_asset_library import digest, ids
from cavi_blender_mcp.blender_node_inputs import InputStore

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('instance_variant_fixture.py')))
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'baseline.blend'))
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'variant-context',
        'expected_project': state['project_id']})['lease_id']

    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})

    source = bridge.dispatch('inspect_asset_library', {'path': 'variant-kit.blend'})
    loaded = edit('append_asset_library_instances', path='variant-kit.blend', names=['EditableKit'], expected_sha256=source['sha256'])
    a = loaded['instances'][0]['name']
    objects = {i['source_name']: bpy.data.objects[i['name']] for i in loaded['items'] if i['id_type'] == 'OBJECT'}
    fence, rig, skin = objects['Fence.001'], objects['LibraryRig'], objects['LibrarySkin']
    count = next(s.identifier for s in fence.modifiers[0].node_group.interface.items_tree if s.name == 'Count')
    finish = next(s.identifier for s in fence.modifiers[0].node_group.interface.items_tree if s.name == 'Finish')
    edit('set_instance_geometry_inputs', name=fence.name, instance=a, modifier='Generator', inputs={count: 5})
    edit('duplicate_object', name=a, new_name='Kit_B', linked=True)
    edit('transform_object', name='Kit_B', location=[4, 1, 0], rotation_degrees=[15, 0, 90], scale=[-1.2, .8, 1.1])
    bpy.context.view_layer.update()
    b = bpy.data.objects['Kit_B']
    collection, matrix = b.instance_collection, b.matrix_world.copy()
    before = ids()
    context = bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    # Fail after native loading and rebinding, before the receipt can be returned.
    with patch.object(variants, 'info', side_effect=RuntimeError('receipt failure')):
        try:
            edit('make_instance_unique', name='Kit_B', new_name='FailedVariant')
        except RuntimeError:
            pass
        else:
            raise AssertionError('Injected failure did not propagate')
    assert ids() == before, {'added': [(v.id_type, v.name) for v in ids()-before],
                             'removed': [(v.id_type, v.name) for v in before-ids()]}
    assert b.instance_collection == collection
    assert b.matrix_world == matrix, {'before': [list(row) for row in matrix], 'after': [list(row) for row in b.matrix_world]}
    assert not list(root.glob('.cavi-variant-*'))
    result = edit('make_instance_unique', name='Kit_B', new_name='TunedKit')
    assert context == (bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    assert b.matrix_world == matrix and bpy.data.objects[a].instance_collection == collection
    assert b.instance_collection.asset_data is not None
    copied = {i['source_name']: bpy.data.objects[i['name']] for i in result['items'] if i['id_type'] == 'OBJECT'}
    new_fence, new_rig, new_skin = copied[fence.name], copied[rig.name], copied[skin.name]
    assert new_skin.parent == new_rig and new_skin.modifiers[0].object == new_rig
    assert new_rig.animation_data.action != rig.animation_data.action
    assert new_fence.modifiers[0].node_group != fence.modifiers[0].node_group
    assert new_fence.modifiers[0].node_group.asset_data is not None
    assert InputStore(new_fence.modifiers[0]).get(count) == 5
    material, new_material = InputStore(fence.modifiers[0]).get(finish), InputStore(new_fence.modifiers[0]).get(finish)
    assert new_material != material
    images = [n.image for n in material.node_tree.nodes if n.type == 'TEX_IMAGE']
    new_images = [n.image for n in new_material.node_tree.nodes if n.type == 'TEX_IMAGE']
    assert not set(images) & set(new_images)
    packed = next(i for i in images if i.packed_file)
    new_packed = next(i for i in new_images if i.packed_file)
    packed_hash = hashlib.sha256(packed.packed_file.data).hexdigest()
    assert hashlib.sha256(new_packed.packed_file.data).hexdigest() == packed_hash
    external = next(i for i in images if not i.packed_file)
    new_external = next(i for i in new_images if not i.packed_file)
    assert external.source == new_external.source == 'FILE'
    assert Path(bpy.path.abspath(external.filepath)).resolve() == Path(bpy.path.abspath(new_external.filepath)).resolve()
    assert external.colorspace_settings.name == new_external.colorspace_settings.name == 'Non-Color'
    expected = json.loads((root/'variant-expected.json').read_text())
    assert digest(root/'normal.exr') == expected['external_sha256']
    edit('set_instance_geometry_inputs', name=new_fence.name, instance='Kit_B', modifier='Generator', inputs={count: 7})
    assert InputStore(fence.modifiers[0]).get(count) == 5
    assert digest(root/'variant-kit.blend') == source['sha256']
    original_fence, variant_fence = fence.name, new_fence.name
    edit('save_project', path='consumer.blend')
    bpy.ops.wm.open_mainfile(filepath=str(root/'consumer.blend'))
    assert bpy.data.objects[a].instance_collection != bpy.data.objects['Kit_B'].instance_collection
    assert InputStore(bpy.data.objects[original_fence].modifiers[0]).get(count) == 5
    assert InputStore(bpy.data.objects[variant_fence].modifiers[0]).get(count) == 7
    assert not list(root.glob('.cavi-variant-*'))
    print(json.dumps({'blender': bpy.app.version_string, 'failed_fork_restored_pointer_and_ids': True,
        'context_and_transform_preserved': True, 'rig_skin_action_remapped': True,
        'packed_texture_sha256': packed_hash, 'external_texture_sha256': expected['external_sha256'],
        'native_asset_metadata_preserved': True, 'independent_overrides_survived_reopen': [5, 7],
        'temporary_snapshot_removed': True}))

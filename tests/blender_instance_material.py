"""Native slot rollback, shared geometry, texture precision and saved overrides."""

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
from cavi_blender_mcp import blender_materials as materials
from cavi_blender_mcp.blender_asset_library import ids

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('instance_material_fixture.py')))
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'baseline.blend'))
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'material-context',
        'expected_project': state['project_id']})['lease_id']

    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})

    source = bridge.dispatch('inspect_asset_library', {'path': 'kit.blend'})
    loaded = edit('append_asset_library_instances', path='kit.blend', names=['GardenKit'], expected_sha256=source['sha256'])
    a = loaded['instances'][0]['name']
    edit('duplicate_object', name=a, new_name='Kit_B', linked=True)
    fork = edit('make_instance_unique', name='Kit_B', new_name='FinishedKit')
    copied = {i['source_name']: bpy.data.objects[i['name']] for i in fork['items'] if i['id_type'] == 'OBJECT'}
    base, trim = copied['BaseStone'], copied['TrimStone']
    shared_data = base.data
    old_material = base.material_slots[0].material
    assert base.data == trim.data and shared_data.users == 2
    context = bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    before = ids()
    with patch.object(materials.json, 'dumps', side_effect=RuntimeError('configuration failure')):
        try:
            edit('assign_instance_material', names=[base.name, trim.name], material_name='FailedFinish',
                 instance='Kit_B', link_mode='OBJECT', normal_texture='normal.png')
        except RuntimeError as exc:
            assert str(exc) == 'configuration failure', str(exc)
        else:
            raise AssertionError('Injected binding failure succeeded')
    assert ids() == before
    assert all(v.material_slots[0].link == 'DATA' and v.material_slots[0].material == old_material for v in [base, trim])
    result = edit('assign_instance_material', names=[base.name], material_name='VariantFinish',
        instance='Kit_B', link_mode='OBJECT', base_color_texture='color.png',
        normal_texture='normal.png', roughness_texture='roughness.png', normal_strength=.6,
        uv_scale=[2., 1.5])
    updated = edit('assign_instance_material', names=[base.name], material_name='VariantFinish',
        instance='Kit_B', update_existing=True, normal_strength=.7)
    assert updated['bindings'][0]['link_mode'] == 'OBJECT'
    assert base.data == trim.data == shared_data and shared_data.users == 2
    assert base.material_slots[0].link == 'OBJECT'
    assert trim.material_slots[0].material == old_material and shared_data.materials[0] == old_material
    material = base.material_slots[0].material
    hashes = {}
    for node in material.node_tree.nodes:
        if node.type != 'TEX_IMAGE':
            continue
        image = node.image
        name = {'Base Color': 'color', 'Normal': 'normal', 'Roughness': 'roughness'}[node.label]
        payload = (root/(name+'.png')).read_bytes()
        assert image.packed_file.data == payload and payload[24] == 16
        hashes[name] = hashlib.sha256(payload).hexdigest()
        assert image.colorspace_settings.name == ('sRGB' if name == 'color' else 'Non-Color')
        if name == 'normal':
            assert abs(image.pixels[0]-32768/65535) < 2e-6
    assert len(hashes) == 3
    normal = next(n for n in material.node_tree.nodes if n.type == 'NORMAL_MAP')
    assert abs(normal.inputs['Strength'].default_value-.7) < 1e-6
    assert context == (bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    # Empty shared meshes can reserve a data slot without binding siblings.
    data = bpy.data.meshes.new('EmptySlots')
    data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    objects = [bpy.data.objects.new(name, data) for name in ['EmptyA', 'EmptyB']]
    for value in objects:
        bpy.context.scene.collection.objects.link(value)
    before = ids()
    with patch.object(materials.json, 'dumps', side_effect=RuntimeError('configuration failure')):
        try:
            edit('assign_object_material', names=['EmptyA', 'EmptyB'], material_name='FailedEmpty', link_mode='OBJECT')
        except RuntimeError as exc:
            assert str(exc) == 'configuration failure', str(exc)
        else:
            raise AssertionError('Injected empty-slot failure succeeded')
    assert ids() == before, {'added': [(v.id_type, v.name) for v in ids()-before]}
    assert not data.materials, len(data.materials)
    assert all(not v.material_slots for v in objects), [(v.name, len(v.material_slots)) for v in objects]
    empty = edit('assign_object_material', names=['EmptyA'], material_name='EmptyFinish', link_mode='OBJECT')
    assert empty['reserved_empty_slots'] == [data.name]
    assert objects[0].material_slots[0].link == 'OBJECT' and objects[1].material_slots[0].material is None
    legacy = edit('assign_material', names=['Cube'], material_name='LegacyFinish', roughness=.4)
    assert legacy['bindings'][0]['link_mode'] == 'DATA'
    base_name, trim_name = base.name, trim.name
    edit('save_project', path='finished.blend')
    bpy.ops.wm.open_mainfile(filepath=str(root/'finished.blend'))
    base, trim = bpy.data.objects[base_name], bpy.data.objects[trim_name]
    assert base.data == trim.data and base.material_slots[0].link == 'OBJECT'
    assert base.material_slots[0].material.name == 'VariantFinish' and trim.material_slots[0].material.name != 'VariantFinish'
    print(json.dumps({'blender': bpy.app.version_string, 'failed_bindings_restored_ids_and_slots': True,
        'empty_shared_slot_rollback': True, 'unassigned_sibling_preserved': True,
        'shared_mesh_preserved': True, 'texture_bit_depth': 16, 'packed_texture_hashes': hashes,
        'normal_and_roughness_non_color': True, 'object_override_survived_reopen': True,
        'legacy_data_assignment': True}))

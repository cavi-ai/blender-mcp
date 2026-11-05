"""Native UDIM rollback, exact packing, Cycles sampling and source-free reopen."""

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
from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_asset_library import ids
from cavi_blender_mcp.blender_materials import CONFIG_TAG

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('shader_udim_fixture.py')))
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'baseline.blend'))
    common = {'material_name':'ArtistFinish', 'group_path':['Finish Controls','Inner Layer'], 'node':'Pattern'}
    initial = shader.inspect(common)
    before_ids = ids()
    context = bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    state = bridge.dispatch('session_control', {'action':'inspect'})
    lease = bridge.dispatch('session_control', {'action':'claim','owner':'udim-native',
        'expected_project':state['project_id']})['lease_id']
    def edit(path='glaze.<UDIM>.exr', numbers=None):
        return bridge.dispatch('owned_edit', {'operation':'set_material_image', 'params':{
            **common, 'image':{'path':path,'color_space':'Non-Color','tiles':numbers or [1001,1002,1011]},
            'lease_id':lease}})
    configs = {n:bpy.data.materials[n][CONFIG_TAG] for n in ['ManagedA','ManagedB']}
    with patch.object(shader, 'node_report', side_effect=RuntimeError('receipt failure')):
        try:
            edit()
        except RuntimeError as exc:
            assert str(exc) == 'receipt failure'
        else:
            raise AssertionError('Injected receipt failure succeeded')
    assert ids() == before_ids and shader.inspect(common) == initial
    for name, config in configs.items():
        assert bpy.data.materials[name][CONFIG_TAG] == config
        assert shader.PROVENANCE_TAG not in bpy.data.materials[name]
    assert not list(root.glob('.cavi-udim-*'))
    png = edit('glaze.<UDIM>.png')
    assert png['links'] == initial['links'] and png['managed_materials_detached'] == ['ManagedA','ManagedB']
    assert all((root/t['path']).read_bytes()[24] == 16 for t in png['image_source']['tiles'])
    assert context == (bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    image = shader.target(common)[1].nodes['Pattern'].image
    assert [t.number for t in image.tiles] == [1001,1002,1011]
    assert not edit('glaze.<UDIM>.png')['changed_image']
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    scene.render.resolution_x = scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '16'
    scene.render.filepath = str(root/'tile-sampling.png')
    bpy.ops.render.render(write_still=True)
    capture = bpy.data.images.load(str(root/'tile-sampling.png'), check_existing=False)
    samples = {}
    for number, x, y in [(1001,16,16),(1002,48,16),(1011,16,48),(1012,48,48)]:
        index = (y*64+x)*4
        samples[number] = list(capture.pixels[index:index+3])
    bpy.data.images.remove(capture)
    for number, channel in [(1001,0),(1002,1),(1011,2)]:
        color = samples[number]
        assert color[channel] > .5 and all(color[channel] > c+.3 for i,c in enumerate(color) if i != channel), samples
    missing = samples[1012]
    assert missing[0] > .8 and missing[2] > .8 and missing[1] < .05, samples
    hdr = edit('alias.<UDIM>.exr')
    assert all(t['path'].startswith('alias.') for t in hdr['image_source']['tiles'])
    image = shader.target(common)[1].nodes['Pattern'].image
    floats = list(image.pixels[:4])
    assert image.is_float and floats[1] < 0 and floats[2] > 1, floats
    before = shader.inspect(common)
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'authored.blend'))
    for tile in hdr['image_source']['tiles']:
        source = root/tile['path']
        resolved = source.resolve()
        source.unlink()
        if resolved != source:
            resolved.unlink()
    bpy.ops.wm.open_mainfile(filepath=str(root/'authored.blend'))
    assert shader.inspect(common) == before
    image = shader.target(common)[1].nodes['Pattern'].image
    assert list(image.pixels[:4]) == floats
    assert not list(root.glob('.cavi-udim-*'))
    print(json.dumps({'native_shader_udim':'passed','png_bit_depth':16,'float_hdr_samples':floats,
        'cycles_cpu_tile_samples':samples,'undeclared_neighbor_uses_missing_tile_fallback':True,
        'failed_receipt_restores_ids_bindings_and_tags':True,'context_preserved':True,
        'packed_tiles_survive_source_free_reopen':True,'temporary_snapshots_removed':True}))

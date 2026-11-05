"""Read-only coverage catches a rendered missing tile and checks its declared repair."""

import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_asset_library import ids

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('udim_coverage_fixture.py')))
    common = {'material_name':'ArtistFinish','group_path':['Finish Controls','Inner Layer'],'node':'Pattern'}
    def image_spec(numbers):
        return {'path':'glaze.<UDIM>.png','tiles':numbers,'color_space':'Non-Color'}
    bound = shader.set_image({**common,'image':image_spec([1001,1002,1011])}, root)
    image = bound['nodes'][0]['image']['name']
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'baseline.blend'))
    state = bridge.dispatch('session_control', {'action':'inspect'})
    lease = bridge.dispatch('session_control', {'action':'claim','owner':'texture-author',
        'expected_project':state['project_id']})['lease_id']
    names = ['TileGrid','OtherSurface']
    def snapshot():
        return {'file':bpy.data.filepath,'dirty':bpy.data.is_dirty,'ids':ids(),
            'active':bpy.context.view_layer.objects.active,'selected':set(bpy.context.selected_objects),
            'meshes':{n:{'vertices':[tuple(v.co) for v in bpy.data.objects[n].data.vertices],
                'faces':[(tuple(p.vertices),p.material_index) for p in bpy.data.objects[n].data.polygons],
                'uvs':[[tuple(v.uv) for v in u.data] for u in bpy.data.objects[n].data.uv_layers],
                'active_uv':bpy.data.objects[n].data.uv_layers.active_index,
                'render_uv':[u.active_render for u in bpy.data.objects[n].data.uv_layers],
                'slots':[(s.link,s.material.name if s.material else None) for s in bpy.data.objects[n].material_slots]}
                for n in names}}
    def inspect(**options):
        return bridge.dispatch('inspect_udim_coverage', {'names':names,'udim_image':image,
            'material':'ArtistFinish', **options})
    before = snapshot()
    missing = inspect()
    assert missing['complete'] and not missing['coverage']['passed']
    assert missing['coverage']['missing_tiles'] == [1012]
    assert [o['triangles'] for o in missing['objects']] == [2,0]
    assert all(e['object'] == 'TileGrid' and e['face'] == 0 for e in missing['coverage']['examples'])
    bounded = inspect(comparison_budget=1)
    assert not bounded['complete'] and not bounded['coverage']['passed']
    assert bounded['coverage']['unused_tiles'] is None
    named = inspect(uv_layer='CollapsedUV')
    assert named['coverage']['degenerate_triangles'] == 2 and not named['coverage']['passed']
    unavailable = inspect(udim_image='UnavailableTiles')
    assert 1012 in unavailable['coverage']['unavailable_tiles']
    for changes in [{'udim_image':'missing'},{'uv_layer':'missing'},{'material':'missing'}]:
        try:
            inspect(**changes)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid source inspection was accepted')
    assert before == snapshot(), 'Coverage changed source, selection, materials or IDs'
    assert not bpy.data.is_dirty
    assert bridge.dispatch('session_control', {'action':'inspect'})['owner'] == 'texture-author'
    def render(name):
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        scene.cycles.device, scene.cycles.samples = 'CPU', 1
        scene.render.resolution_x = scene.render.resolution_y = 64
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '16'
        scene.render.filepath = str(root/(name+'.png'))
        bpy.ops.render.render(write_still=True)
        capture = bpy.data.images.load(scene.render.filepath, check_existing=False)
        index = (48*64+48)*4
        sample = list(capture.pixels[index:index+3])
        bpy.data.images.remove(capture)
        return sample
    missing_pixel = render('missing')
    assert missing_pixel[0] > .8 and missing_pixel[2] > .8 and missing_pixel[1] < .05, missing_pixel
    fixed = bridge.dispatch('owned_edit', {'operation':'set_material_image','params':{
        **common,'image':image_spec([1001,1002,1011,1012]),'lease_id':lease}})
    image = fixed['nodes'][0]['image']['name']
    repaired = inspect()
    assert repaired['complete'] and repaired['coverage']['passed']
    repaired_pixel = render('repaired')
    assert repaired_pixel[0] > .5 and repaired_pixel[1] > .5 and repaired_pixel[2] < .1, repaired_pixel
    print(json.dumps({'native_udim_coverage':'passed','missing_tile':[1012],
        'cycles_cpu_missing_pixel':missing_pixel,'cycles_cpu_repaired_pixel':repaired_pixel,
        'coverage_inspection_preserves_source_selection_materials_ids':True,'source_uv0_and_named_layer_checked':True,
        'material_object_override_filtered':True,'incomplete_never_passes':True,
        'inspection_preserves_author_lease':True,'affected_faces':missing['coverage']['examples']}))

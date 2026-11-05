"""Native UV edits preserve geometry and reverse partial writes on failure."""
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

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    bridge._workspace = root
    runpy.run_path(str(Path(__file__).with_name('uv_transform_fixture.py')))
    surface = bpy.data.objects['TileGrid']
    mesh = surface.data
    def snapshot():
        return {'mesh':mesh.as_pointer(), 'verts':[tuple(v.co) for v in mesh.vertices],
            'faces':[(tuple(p.vertices),p.material_index,p.select) for p in mesh.polygons],
            'edges':[(tuple(e.vertices),e.use_seam,e.select) for e in mesh.edges],
            'keys':[[tuple(v.co) for v in k.data] for k in mesh.shape_keys.key_blocks],
            'weights':[[(g.group,g.weight) for g in v.groups] for v in mesh.vertices],
            'modifiers':[(m.name,m.type,m.object) for m in surface.modifiers],
            'parent':surface.parent, 'materials':list(mesh.materials),
            'active_uv':mesh.uv_layers.active_index,
            'render_uv':[u.active_render for u in mesh.uv_layers],
            'alternate':[tuple(v.uv) for v in mesh.uv_layers['Alternate'].data],
            'unselected':[tuple(v.uv) for v in mesh.uv_layers['UVMap'].data[4:]],
            'selected':set(bpy.context.selected_objects), 'active':bpy.context.view_layer.objects.active}
    def uvs():
        return [tuple(v.uv) for v in mesh.uv_layers['UVMap'].data]
    state = bridge.dispatch('session_control', {'action':'inspect'})
    lease = bridge.dispatch('session_control', {'action':'claim','owner':'uv-author',
        'expected_project':state['project_id']})['lease_id']
    def edit(transform, **options):
        return bridge.dispatch('owned_edit', {'operation':'transform_uv','params':{
            'name':'TileGrid','uv_layer':'UVMap','transform':transform,'lease_id':lease, **options}})
    original, source = uvs(), snapshot()
    result = edit({'faces':[0],'offset':[-1,-1]})
    assert result['uv_layer'] == 'UVMap'
    assert result['uv_transform']['faces'] == [0] and result['uv_transform']['loops'] == 4
    assert result['uv_transform']['materials'] == ['ArtistFinish']
    assert source == snapshot(), 'UV editing changed geometry, rig, shape keys or context'
    for old, new in zip(original[:4], uvs()[:4], strict=True):
        assert all(abs(new[i]-(old[i]-1)) < 1e-6 for i in range(2))
    edit({'faces':[0],'offset':[1,1]})
    for old, new in zip(original, uvs(), strict=True):
        assert max(abs(a-b) for a,b in zip(old,new,strict=True)) < 1e-6
    # Explicit scale, rotation and pivot: (1.2,1.2) -> (.6,1.4) around (1,1).
    edit({'faces':[0],'scale':[2,2],'rotation_degrees':90,'pivot':[1,1]})
    assert max(abs(a-b) for a,b in zip(uvs()[0],(.6,1.4),strict=True)) < 1e-6
    before = uvs()
    invalid = [{'faces':[2]}, {'faces':[0,0]}, {'faces':[True]}, {'faces':[]},
        {'faces':[0],'offset':[1e30,0]}, {'faces':[0],'scale':[float('nan'),1]},
        {'faces':[0],'unknown':1}]
    for transform in invalid:
        try:
            edit(transform)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Invalid edit accepted: {transform}')
        assert before == uvs() and source == snapshot()
    linked = bpy.data.objects.new('Linked', mesh)
    bpy.context.scene.collection.objects.link(linked)
    try:
        edit({'faces':[0],'offset':[1,0]})
    except ValueError as exc:
        assert 'shared' in str(exc)
    else:
        raise AssertionError('Shared mesh changed without an independent copy')
    bpy.data.objects.remove(linked, do_unlink=True)
    from cavi_blender_mcp import blender_uv_edit
    real_write = blender_uv_edit.write
    def partial(layer, rows):
        real_write(layer, rows[:1])
        raise RuntimeError('partial UV write')
    with patch.object(blender_uv_edit, 'write', partial):
        try:
            edit({'faces':[0],'offset':[1,0]})
        except RuntimeError as exc:
            assert str(exc) == 'partial UV write'
        else:
            raise AssertionError('Injected write failure was ignored')
    assert before == uvs() and source == snapshot(), 'Partial UV write was not rolled back'
    # Persist/reopen proves the edit is native mesh data rather than a cached report.
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'face-uvs.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(root/'face-uvs.blend'))
    reopened = [tuple(v.uv) for v in bpy.data.objects['TileGrid'].data.uv_layers['UVMap'].data]
    assert reopened == before
    print(json.dumps({'native_uv_transform':'passed','topology_skin_keys_context_preserved':True,
        'partial_write_rolled_back':True,'named_layer_and_face_scope_checked':True,
        'scale_rotation_pivot_checked':True,'native_save_reopen_checked':True}))

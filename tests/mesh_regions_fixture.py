"""Artist mesh data and independent native checks for the region-extrusion case."""
import json
import os
from pathlib import Path

import bpy

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
bpy.data.objects.remove(bpy.data.objects['Cube'], do_unlink=True)
mesh = bpy.data.meshes.new('ArtistPanel')
mesh.from_pydata([(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                  (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)], [],
                 [(3,2,1,0),(0,4,7,3),(0,1,5,4),(1,2,6,5),(2,3,7,6),(4,5,6),(4,6,7)])
mesh.update()
panel = bpy.data.objects.new('Panel', mesh)
peer = bpy.data.objects.new('Peer', mesh)
bpy.context.scene.collection.objects.link(panel)
bpy.context.scene.collection.objects.link(peer)
peer.location.x = 4
panel.location = (.2, .1, .5)
panel.rotation_euler = (.1, .2, .3)
panel.scale = (.5, 1.2, 2)
for name in ('Body', 'CapA', 'CapB'):
    mesh.materials.append(bpy.data.materials.new(name))
for f in mesh.polygons:
    f.material_index = f.index - 4 if f.index >= 5 else 0
for label in ('BakeAtlas', 'ArtistUV'):
    layer = mesh.uv_layers.new(name=label)
    for i, loop in enumerate(layer.data):
        loop.uv = (i * .013 + .07, i * .017 + .11)
mesh.uv_layers.active_index = 1
mesh.uv_layers['BakeAtlas'].active_render = True
color = mesh.color_attributes.new(name='ArtistTint', type='FLOAT_COLOR', domain='CORNER')
for i, item in enumerate(color.data):
    item.color = (.1234567 + i * .001, .2345678, .3456789, 1)
mesh['artist_label'] = 'EditablePanel'
panel.material_slots[0].link = 'OBJECT'
panel.material_slots[0].material = bpy.data.materials.new('ObjectFinish')
mesh.edges[0].use_seam = True


def corners(value):
    data = value.data
    result = {}
    for face in data.polygons:
        cap = face.normal.z > .9 and face.center.z > 1.2
        entries = {}
        for li in face.loop_indices:
            co = data.vertices[data.loops[li].vertex_index].co
            key = tuple(round(float(v), 5) for v in (co.x, co.y, co.z - (.4 if cap else 0)))
            entries[key] = ([tuple(data.uv_layers[name].data[li].uv) for name in ('BakeAtlas','ArtistUV')],
                            tuple(data.color_attributes['ArtistTint'].data[li].color))
        result[(face.material_index, tuple(sorted(entries)))] = entries
    return result


baseline = corners(panel)
matrix = [*panel.location, *panel.rotation_euler, *panel.scale]


@bpy.app.handlers.persistent
def verify(*_):
    value = bpy.data.objects.get('Panel')
    if value is None or len(value.data.vertices) != 12:
        return
    observed = corners(value)
    for key, entries in baseline.items():
        assert key in observed, key
        for vertex, (uvs, rgba) in entries.items():
            other_uvs, other_rgba = observed[key][vertex]
            assert all(abs(a-b) < 1e-7 for ua, ub in zip(uvs, other_uvs, strict=True)
                       for a,b in zip(ua, ub, strict=True)), key
            assert all(abs(a-b) < 1e-7 for a,b in zip(rgba, other_rgba, strict=True)), key
    assert [*value.location, *value.rotation_euler, *value.scale] == matrix
    assert value.data['artist_label'] == 'EditablePanel'
    assert value.material_slots[0].link == 'OBJECT'
    assert value.material_slots[0].material.name == 'ObjectFinish'
    assert value.data.uv_layers.active.name == 'ArtistUV'
    assert next(l.name for l in value.data.uv_layers if l.active_render) == 'BakeAtlas'
    assert len(bpy.data.objects['Peer'].data.vertices) == 8
    (root / 'native-check.json').write_text(json.dumps({'file': bpy.data.filepath,
        'artist_uv_and_float_color_preserved': True, 'object_finish_preserved': True,
        'peer_geometry_unchanged': True, 'custom_properties_preserved': True}))


bpy.app.handlers.depsgraph_update_post.append(verify)
bpy.app.handlers.load_post.append(verify)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'initial.blend'), check_existing=False)

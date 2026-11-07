"""Canonical identities for the evaluated mesh candidates used by scene picking."""
import hashlib
import json

import bpy

from .blender_mesh_regions import mesh_digest
from .blender_uv_charts import uv_digest


def candidates(graph):
    for instance in graph.object_instances:
        value,parent=instance.object,instance.parent
        if (value.type!='MESH' or value.original.type!='MESH' or not instance.show_self
                or value.hide_render or not value.visible_camera or not value.data.polygons
                or (parent is not None and (parent.hide_render or not parent.visible_camera))):
            continue
        yield value,{'is_instance':instance.is_instance,'parent':parent.original.name if parent else None,
            'persistent_id':list(instance.persistent_id),
            'matrix_world':[list(row) for row in instance.matrix_world]}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def identity(value):
    return {'name':value.name,'library':value.library.filepath if value.library else None} if value else None


def snapshot():
    if bpy.context.mode!='OBJECT':
        raise ValueError('Geometry identity requires Object Mode')
    bpy.context.view_layer.update()
    graph=bpy.context.evaluated_depsgraph_get()
    meshes,placements={},[]
    vertices=triangles=edges=loops=0
    for value,instance in candidates(graph):
        key=value.data.as_pointer()
        if key not in meshes:
            data=value.data
            vertices+=len(data.vertices)
            triangles+=sum(max(0,len(f.vertices)-2) for f in data.polygons)
            edges+=len(data.edges)
            loops+=len(data.loops)
            if vertices>500000 or triangles>500000 or edges>1500000 or loops>1500000:
                raise ValueError('Geometry identity exceeds the evaluated mesh budget')
            mesh=value.to_mesh(preserve_all_data_layers=True,depsgraph=graph)
            try:
                meshes[key]=digest({'surface':mesh_digest(mesh),'active_uv':mesh.uv_layers.active_index,
                    'uvs':[[layer.name,layer.active_render,uv_digest(layer)] for layer in mesh.uv_layers]})
            finally:
                value.to_mesh_clear()
        placements.append(digest({'object':identity(value.original),'mesh':identity(value.original.data),
            'instance':instance,'geometry':meshes[key],
            'materials':[[slot.link,identity(slot.material)] for slot in value.material_slots]}))
    scene=bpy.context.scene
    return {'available':True,'scope':'evaluated_view_layer_mesh_geometry',
        'sha256':digest({'version':1,'scene':scene.name,'view_layer':bpy.context.view_layer.name,
            'scene_unit_meters':scene.unit_settings.scale_length,'placements':sorted(placements)}),
        'geometry_counts':{'placements':len(placements),'unique_meshes':len(meshes),
            'vertices':vertices,'triangles':triangles},
        'not_checked':['shader_parameters','image_content','lighting','shader_opacity',
            'non_mesh_geometry','render_only_visibility','render_modifier_differences']}


def capture():
    try:
        return snapshot()
    except (ValueError,TypeError,RuntimeError) as exc:
        return {'available':False,'reason':str(exc)}

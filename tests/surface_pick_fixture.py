"""A posed triangle with corner UVs, mirrored scale and independent world-ray references."""
import json
import os
from pathlib import Path

import bpy
from mathutils import Vector

root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj,do_unlink=True)
mesh=bpy.data.meshes.new('PickTriangle')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(-1,1,0)],[],[(0,1,2)])
obj=bpy.data.objects.new('PickTarget',mesh)
bpy.context.scene.collection.objects.link(obj)
obj.location=(7,2,3)
obj.rotation_euler=(.2,.1,.3)
obj.scale=(-2,3,1)
uv=mesh.uv_layers.new(name='SourceUV')
for row,point in zip(uv.data,[(.1,.2),(.9,.2),(.1,.8)],strict=True):
    row.uv=point
uv.data[0].pin_uv=True
obj.shape_key_add(name='Basis')
key=obj.shape_key_add(name='Lift')
key.data[0].co.z=.2
key.value=.5
rig=bpy.data.objects.new('Skeleton',bpy.data.armatures.new('Skeleton'))
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active=rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bone=rig.data.edit_bones.new('Root')
bone.head,bone.tail=(0,0,0),(0,0,1)
bpy.ops.object.mode_set(mode='OBJECT')
rig.pose.bones['Root'].rotation_mode='XYZ'
rig.pose.bones['Root'].rotation_euler.z=.3
group=obj.vertex_groups.new(name='Root')
for i,weight in enumerate((.8,.5,1.)):
    group.add([i],weight,'REPLACE')
modifier=obj.modifiers.new('Skin','ARMATURE')
modifier.object=rig
obj.parent=rig
other=obj.copy()
other.data=obj.data.copy()
other.name='TopoChanged'
bpy.context.scene.collection.objects.link(other)
other.modifiers.new('Topology','ARRAY').count=2
bpy.context.scene.unit_settings.scale_length=.01
bpy.context.scene.frame_set(3,subframe=.25)
bpy.context.view_layer.update()


def reference(evaluated):
    value=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()) if evaluated else obj
    points=[v.co.copy() for v in value.data.vertices]
    point=sum((p*w for p,w in zip(points,(.2,.3,.5),strict=True)),Vector())
    normal=(points[1]-points[0]).cross(points[2]-points[0]).normalized()
    normal=(value.matrix_world.inverted().transposed().to_3x3()@normal).normalized()
    world=value.matrix_world@point
    return {'ray':{'origin_world':list(world+normal*2),'direction_world':list(-normal),
                   'max_distance_m':.03,'evaluated':evaluated},
            'position_world':list(world),'position_local':list(point),'normal_world':list(normal),
            'uv':[.34,.5],'distance_m':.02}


(root/'pick-reference.json').write_text(json.dumps({'source':reference(False),'evaluated':reference(True)}))


@bpy.app.handlers.persistent
def audit(*_):
    (root/'pick-audit.json').write_text(json.dumps({
        'vertices':[list(v.co) for v in mesh.vertices],
        'keys':[[list(p.co) for p in k.data] for k in mesh.shape_keys.key_blocks],
        'values':[k.value for k in mesh.shape_keys.key_blocks],
        'uvs':[list(row.uv) for row in uv.data], 'pins':[row.pin_uv for row in uv.data],
        'weights':[[(g.group,g.weight) for g in v.groups] for v in mesh.vertices],
        'matrix':[list(row) for row in obj.matrix_world],
        'pose':list(rig.pose.bones['Root'].rotation_euler),
        'selected':sorted(o.name for o in bpy.context.selected_objects),
        'active':bpy.context.view_layer.objects.active.name,'mode':bpy.context.mode,
        'frame':bpy.context.scene.frame_current,'subframe':bpy.context.scene.frame_subframe}))


bpy.app.handlers.save_post.append(audit)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'),check_existing=False)

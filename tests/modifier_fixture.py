"""Editable, rigged shared geometry with independently owned modifier stacks."""
import json
import os
from pathlib import Path

import bpy

root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cube_add()
hero=bpy.context.object
hero.name='Hero'
hero.shape_key_add(name='Basis')
hero.shape_key_add(name='Lift').data[0].co.z+=.2
hero.vertex_groups.new(name='Root').add(list(range(8)),.8,'REPLACE')
armature=bpy.data.armatures.new('Rig')
rig=bpy.data.objects.new('Rig',armature)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active=rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bone=armature.edit_bones.new('Root')
bone.head, bone.tail=(0,0,0),(0,0,1)
bpy.ops.object.mode_set(mode='OBJECT')
hero.modifiers.new('Skin','ARMATURE').object=rig
bevel=hero.modifiers.new('HeroRound','BEVEL')
bevel.width,bevel.segments=.05,3
decimate=hero.modifiers.new('FinishReduction','DECIMATE')
decimate.ratio=.8
hero.keyframe_insert('location',frame=1)
hero.keyframe_insert('location',frame=10)
peer=hero.copy()
peer.name='Peer'
bpy.context.collection.objects.link(peer)
for name,kind in [('Subdiv','SUBSURF'),('Voxel','REMESH')]:
    value=hero.copy()
    value.data=hero.data.copy()
    value.name=name
    value.shape_key_clear()
    value.modifiers.clear()
    modifier=value.modifiers.new(name,kind)
    if kind=='SUBSURF':modifier.levels=modifier.render_levels=1
    else:modifier.mode='VOXEL';modifier.voxel_size=.2
    bpy.context.collection.objects.link(value)

grid=bpy.data.meshes.new('BudgetGrid')
grid.from_pydata([(x/50,y/50,0) for y in range(101) for x in range(101)],[],
    [(y*101+x,y*101+x+1,(y+1)*101+x+1,(y+1)*101+x) for y in range(100) for x in range(100)])
big=bpy.data.objects.new('BudgetGrid',grid)
bpy.context.collection.objects.link(big)
modifier=big.modifiers.new('Subdivision','SUBSURF')
modifier.levels=modifier.render_levels=1

for name in ('Animated','NlaAnimated','Driven','Referenced'):
    value=bpy.data.objects.new(name,hero.data)
    bpy.context.collection.objects.link(value)
    controlled=value.modifiers.new('Controlled','BEVEL')
    controlled.width=.05
    if name=='Animated':controlled.keyframe_insert('width',frame=1)
    if name=='NlaAnimated':
        controlled.keyframe_insert('width',frame=1)
        animation=value.animation_data
        action,slot=animation.action,animation.action_slot
        strip=animation.nla_tracks.new().strips.new('Width',1,action)
        strip.action_slot=slot
        animation.action=None
    if name=='Driven':controlled.driver_add('width').driver.expression='0.05'
reader=bpy.data.objects.new('Reader',None)
bpy.context.collection.objects.link(reader)
reader['width']=0.
driver=reader.driver_add('["width"]').driver
variable=driver.variables.new()
variable.type='SINGLE_PROP'
variable.targets[0].id=bpy.data.objects['Referenced']
variable.targets[0].data_path='modifiers[0].width'
driver.expression=variable.name


@bpy.app.handlers.persistent
def audit(*_):
    result={}
    for name in ('Hero','Peer','Subdiv','Voxel','BudgetGrid','Animated','NlaAnimated','Driven','Referenced'):
        value=bpy.data.objects[name]
        mesh=value.data
        result[name]={'mesh':mesh.name,'users':mesh.users,
            'vertices':[list(v.co) for v in mesh.vertices],
            'faces':[list(f.vertices) for f in mesh.polygons],
            'uvs':{l.name:[list(c.uv) for c in l.data] for l in mesh.uv_layers},
            'weights':[[(g.group,g.weight) for g in v.groups] for v in mesh.vertices],
            'keys':{k.name:[list(c.co) for c in k.data] for k in mesh.shape_keys.key_blocks} if mesh.shape_keys else {},
            'rig_bindings':[(m.name,m.object.name if m.object else None) for m in value.modifiers if m.type=='ARMATURE'],
            'stack':[(m.name,m.type) for m in value.modifiers]}
    result['context']={'selected':sorted(o.name for o in bpy.context.selected_objects),
        'active':bpy.context.view_layer.objects.active.name,'mode':bpy.context.mode}
    (root/'modifier-audit.json').write_text(json.dumps(result))


bpy.app.handlers.save_post.append(audit)
bpy.app.handlers.load_post.append(audit)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'))

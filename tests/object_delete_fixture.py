"""A small object lifecycle with shared geometry and real dependency boundaries."""
import json
import os
from pathlib import Path

import bpy

root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
scene=bpy.context.scene
for value in list(bpy.data.objects): bpy.data.objects.remove(value,do_unlink=True)
mesh=bpy.data.meshes.new('SharedMesh')
mesh.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
uv=mesh.uv_layers.new(name='UVMap')
for index,value in enumerate([(0,0),(1,0),(0,1)]): uv.data[index].uv=value
material=bpy.data.materials.new('SharedFinish')
material.diffuse_color=(.2,.4,.6,1)
mesh.materials.append(material)


def object(name,data=None,parent=None,collection=None):
    value=bpy.data.objects.new(name,data)
    (collection or scene.collection).objects.link(value)
    value.parent=parent
    return value


object('Draft',mesh)
keep=object('Keep',mesh)
keep.location=(3,2,1)
keep.select_set(True)
bpy.context.view_layer.objects.active=keep
hierarchy=object('Hierarchy')
object('HierarchyChild',mesh,hierarchy)
branch=object('HierarchyBranch',parent=hierarchy)
object('HierarchyGrandchild',mesh,branch)
blocked=object('BlockedRoot')
object('FreeChild',mesh,blocked)
control=object('Control',parent=blocked)
constraint=keep.constraints.new('COPY_LOCATION')
constraint.name='PreservedControl'
constraint.target=control
constraint.influence=.25
cross=object('CrossScene',mesh)
other=bpy.data.scenes.new('OtherScene')
other.collection.objects.link(cross)
kit=bpy.data.collections.new('Kit')
scene.collection.children.link(kit)
working=bpy.data.collections.new('Working')
scene.collection.children.link(working)
object('CollectionDraft',mesh,collection=working)
scene_bound=object('SceneBound',mesh)
scene['ProtectedObject']=scene_bound
metadata_bound=object('MetadataBound',mesh)
kit['ProtectedObject']=metadata_bound
object('KitDefinition',mesh,collection=kit)
placement=object('KitPlacement')
placement.instance_type='COLLECTION'
placement.instance_collection=kit
bpy.context.view_layer.update()


@bpy.app.handlers.persistent
def audit(*_):
    current=bpy.context.scene
    record={'scene':current.name,'active':bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        'objects':{value.name:{'type':value.type,'matrix':[list(row) for row in value.matrix_world],
            'parent':value.parent.name if value.parent else None,'selected':value.select_get(),
            'data':value.data.name if value.data else None,
            'constraints':[[c.name,c.type,c.target.name if getattr(c,'target',None) else None,c.influence] for c in value.constraints]}
            for value in bpy.data.objects},
        'meshes':{value.name:{'vertices':[list(v.co) for v in value.vertices],
            'faces':[list(p.vertices) for p in value.polygons],
            'uv':{layer.name:[list(v.uv) for v in layer.data] for layer in value.uv_layers},
            'materials':[m.name if m else None for m in value.materials],'users':value.users} for value in bpy.data.meshes if value.users},
        'materials':{value.name:list(value.diffuse_color) for value in bpy.data.materials if value.users},
        'scenes':{value.name:sorted(o.name for o in value.objects) for value in bpy.data.scenes},
        'scene_refs':{s.name:{key:value.name for key,value in s.items() if isinstance(value,bpy.types.Object)} for s in bpy.data.scenes},
        'collection_refs':{c.name:{key:value.name for key,value in c.items() if isinstance(value,bpy.types.Object)} for c in bpy.data.collections},
        'collections':{value.name:sorted(o.name for o in value.objects) for value in bpy.data.collections}}
    (root/'deletion-audit.json').write_text(json.dumps(record))


bpy.app.handlers.save_post.append(audit)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'),check_existing=False)

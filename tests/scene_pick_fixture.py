"""Independent rendered references for occlusion, material overrides and instances."""
import json
import os
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
scene=bpy.context.scene
for value in list(bpy.data.objects):
    bpy.data.objects.remove(value,do_unlink=True)


def finish(name,color):
    material=bpy.data.materials.new(name)
    material.use_nodes=True
    nodes=material.node_tree.nodes
    nodes.clear()
    signal=nodes.new('ShaderNodeEmission')
    signal.inputs['Color'].default_value=(*color,1)
    output=nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(signal.outputs[0],output.inputs['Surface'])
    return material


def panel(name,position,material,collection=None):
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[],[(0,1,2,3)])
    layer=mesh.uv_layers.new(name='UVMap')
    for index,uv in enumerate([(0,0),(1,0),(1,1),(0,1)]): layer.data[index].uv=uv
    mesh.materials.append(material)
    value=bpy.data.objects.new(name,mesh)
    (collection or scene.collection).objects.link(value)
    value.location=position
    return value


red=finish('InstanceFinish',(1,.03,.03))
green=finish('ObjectFinish',(.03,1,.03))
blue=finish('GeneratedFinish',(.03,.03,1))
panel('Rear',(0,0,0),red)
front=panel('Foreground',(0,0,1),red)
front.material_slots[0].link='OBJECT'
front.material_slots[0].material=green
panel('HiddenOccluder',(0,0,2),blue).hide_render=True
panel('CameraHiddenOccluder',(0,0,3),blue).visible_camera=False
generated=panel('Generated',(-4,0,0),blue)
modifier=generated.modifiers.new('Subdivision','SUBSURF')
modifier.subdivision_type='SIMPLE'
modifier.levels=modifier.render_levels=1
prototype=bpy.data.collections.new('PrototypeCollection')
panel('Prototype',(0,0,0),red,prototype)
instance=bpy.data.objects.new('InstancePlacement',None)
instance.instance_type='COLLECTION'
instance.instance_collection=prototype
instance.location=(4,0,0)
instance.scale=(-1.5,1,2)
scene.collection.objects.link(instance)
hidden_instance=bpy.data.objects.new('HiddenPlacement',None)
hidden_instance.instance_type='COLLECTION'
hidden_instance.instance_collection=prototype
hidden_instance.location=(0,0,4)
hidden_instance.hide_render=True
scene.collection.objects.link(hidden_instance)
camera=bpy.data.objects.new('Review',bpy.data.cameras.new('Review'))
scene.collection.objects.link(camera)
camera.location=(0,0,8)
camera.data.type='ORTHO'
camera.data.ortho_scale=12
camera.data.clip_start,camera.data.clip_end=.1,20
scene.camera=camera
scene.render.engine='CYCLES'
scene.cycles.device='CPU'
scene.cycles.samples=1
scene.cycles.use_denoising=False
scene.render.threads_mode='FIXED'
scene.render.threads=2
scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage=96,32,100
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGBA'
scene.render.image_settings.color_depth='16'
scene.render.film_transparent=True
scene.view_settings.view_transform='Standard'
bpy.context.view_layer.update()
references={}
for name,point,color in [('Foreground',(-.4,-.2,1),1),('Prototype',(4.6,-.2,0),0),('Generated',(-4.4,-.2,0),2)]:
    p=world_to_camera_view(scene,camera,Vector(point))
    references[name]={'camera':'Review','image_size':[96,32],
        'pixel':[p.x*96-.5,(1-p.y)*32-.5],'world':point,'channel':color}
(root/'references.json').write_text(json.dumps(references))
scene.render.filepath=str(root/'review.png')
bpy.ops.render.render(write_still=True)
image=bpy.data.images.load(str(root/'review.png'),check_existing=False)
samples={}
for name,ref in references.items():
    x,y=(round(v) for v in ref['pixel'])
    offset=((31-y)*96+x)*4
    samples[name]=list(image.pixels[offset:offset+4])
bpy.data.images.remove(image)
(root/'samples.json').write_text(json.dumps(samples))


@bpy.app.handlers.persistent
def audit(*_):
    (root/'audit.json').write_text(json.dumps({
        'frame':scene.frame_current,'active':bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        'objects':{o.name:{'matrix':[list(row) for row in o.matrix_world],
            'selected':o.select_get(),'hidden':o.hide_render,
            'vertices':[list(v.co) for v in o.data.vertices] if o.type=='MESH' else None,
            'uv':[list(v.uv) for v in o.data.uv_layers[0].data] if o.type=='MESH' else None,
            'materials':[slot.material.name if slot.material else None for slot in o.material_slots]}
            for o in bpy.data.objects}}))


bpy.app.handlers.save_post.append(audit)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'),check_existing=False)

"""Independent forward-projected pixel references and native PNG sample observers."""
import json
import os
import runpy
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
runpy.run_path(str(Path(__file__).with_name('surface_pick_fixture.py')))
scene=bpy.context.scene
target=bpy.data.objects['PickTarget']
bpy.data.objects['TopoChanged'].hide_render=True
evaluated=target.evaluated_get(bpy.context.evaluated_depsgraph_get())
point=sum((v.co*w for v,w in zip(evaluated.data.vertices,(.2,.3,.5),strict=True)),Vector())
world=evaluated.matrix_world@point
normal=(evaluated.data.vertices[1].co-evaluated.data.vertices[0].co).cross(
    evaluated.data.vertices[2].co-evaluated.data.vertices[0].co).normalized()
normal=(evaluated.matrix_world.inverted().transposed().to_3x3()@normal).normalized()
material=bpy.data.materials.new('PixelSignal')
material.use_nodes=True
nodes=material.node_tree.nodes
nodes.clear()
emission=nodes.new('ShaderNodeEmission')
emission.inputs['Color'].default_value=(1,.05,.1,1)
output=nodes.new('ShaderNodeOutputMaterial')
material.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
target.data.materials.append(material)
cameras=[]
for name,kind,shift in [('Perspective','PERSP',(.11,-.08)),('Orthographic','ORTHO',(.16,.07))]:
    camera=bpy.data.objects.new(name,bpy.data.cameras.new(name))
    scene.collection.objects.link(camera)
    camera.location=world+normal*5
    camera.rotation_euler=(world-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.scale=(2,3,4)
    camera.data.type=kind
    camera.data.shift_x,camera.data.shift_y=shift
    camera.data.clip_start,camera.data.clip_end=.1,20
    camera.data.ortho_scale=6
    cameras.append(camera)
bpy.context.view_layer.update()
for name,depth in [('NearClip',.05),('FarClip',25)]:
    mesh=bpy.data.meshes.new(name)
    matrix=cameras[0].matrix_world.normalized()
    mesh.from_pydata([matrix@Vector(v) for v in [(-100,-100,-depth),(100,-100,-depth),(0,100,-depth)]],[],[(0,1,2)])
    scene.collection.objects.link(bpy.data.objects.new(name,mesh))
pano=bpy.data.objects.new('Panorama',bpy.data.cameras.new('Panorama'))
pano.data.type='PANO'
scene.collection.objects.link(pano)
scene.render.engine='CYCLES'
scene.cycles.device='CPU'
scene.cycles.samples=1
scene.cycles.use_denoising=False
scene.render.threads_mode='FIXED'
scene.render.threads=2
scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage=160,120,50
scene.render.pixel_aspect_x,scene.render.pixel_aspect_y=1.3,1
scene.render.film_transparent=True
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGBA'
scene.render.image_settings.color_depth='16'
scene.view_settings.view_transform='Standard'
references={}
for camera in cameras:
    projected=world_to_camera_view(scene,camera,world)
    references[camera.name]={'camera':camera.name,
        'pixel':[projected.x*80-.5,(1-projected.y)*60-.5],'image_size':[80,60],
        'position_world':list(world),'uv':[.34,.5]}
(root/'camera-reference.json').write_text(json.dumps(references))
scene.camera=cameras[0]
scene.render.filepath=str(root/'initial-camera.png')
bpy.ops.render.render(write_still=True)


def samples(path,reference):
    image=bpy.data.images.load(str(path),check_existing=False)
    try:
        width,height=image.size
        x,y=(round(p) for p in reference['pixel'])
        offset=((height-1-y)*width+x)*4
        rgba=list(image.pixels[offset:offset+4])
        return {'size':[width,height],'rgba':rgba,'bit_depth':path.read_bytes()[24]}
    finally:
        bpy.data.images.remove(image)


(root/'initial-camera-sample.json').write_text(json.dumps(samples(root/'initial-camera.png',references['Perspective'])))


@bpy.app.handlers.persistent
def measure_images(*_):
    paths=[root/(name+'.png') for name in references]
    if not all(path.exists() for path in paths):
        return
    (root/'camera-samples.json').write_text(json.dumps({path.stem:samples(path,references[path.stem]) for path in paths}))
    bpy.app.handlers.save_post.remove(measure_images)


@bpy.app.handlers.persistent
def audit(*_):
    (root/'camera-audit.json').write_text(json.dumps({
        'source':json.loads((root/'pick-audit.json').read_text()),
        'active_camera':scene.camera.name,'raster':[scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage],
        'pixel_aspect':[scene.render.pixel_aspect_x,scene.render.pixel_aspect_y],
        'cameras':{c.name:{'matrix':[list(row) for row in c.matrix_world],
            'lens':c.data.lens,'shift':[c.data.shift_x,c.data.shift_y],
            'clip':[c.data.clip_start,c.data.clip_end],'type':c.data.type} for c in cameras}}))


bpy.app.handlers.save_post.extend([measure_images,audit])
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'),check_existing=False)

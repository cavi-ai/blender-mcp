"""Bake explicit shader values on the original actor into a separate UV atlas."""

from pathlib import Path

import bpy
import numpy as np

from .blender_asset_library import digest
from .blender_bake import MAX_LOW_TRIANGLES, bake_layer, restore, state, triangles, write_png
from .blender_bridge import obj, output_file
from .blender_errors import preflight
from .blender_material_bindings import capture
from .blender_material_bindings import restore as restore_bindings
from .blender_material_variants import clone_graph, dispose_graph
from .blender_shader_channel import locate, route


def validate(p):
    if bpy.context.mode!='OBJECT':
        raise ValueError('Switch Blender to Object Mode before baking')
    value=obj(p['name'],mesh=True)
    if not value.is_editable or not 0<triangles(value)<=MAX_LOW_TRIANGLES:
        raise ValueError(f'Target needs an editable object with 1..{MAX_LOW_TRIANGLES} triangles')
    spec=p.get('source')
    if (not isinstance(spec,dict) or set(spec)-{'material','group_path','node','socket','direction','role'}
            or any(not isinstance(spec.get(k),str) or not spec[k] for k in ['material','node','socket'])):
        raise ValueError('source requires material, node and socket')
    if spec.get('direction','OUTPUT') not in {'INPUT','OUTPUT'} or spec.get('role','data') not in {'data','color'}:
        raise ValueError('source requires INPUT/OUTPUT direction and data/color role')
    groups=spec.get('group_path',[])
    if not isinstance(groups,list) or len(groups)>16 or any(not isinstance(n,str) or not n for n in groups):
        raise ValueError('group_path must list at most 16 nonempty group names')
    material=bpy.data.materials.get(spec['material'])
    slots=[s for s in value.material_slots if s.material==material] if material else []
    if not slots:
        raise ValueError('Source material must be bound to the target mesh')
    locate(material,spec)
    resolution,samples,margin=p.get('resolution',1024),p.get('samples',16),p.get('margin',4)
    for number,low,high,name in [(resolution,64,4096,'resolution'),(samples,1,256,'samples'),(margin,0,64,'margin')]:
        if type(number) is not int or not low<=number<=high:
            raise ValueError(f'{name} must be an integer from {low} to {high}')
    suffix=Path(p['path']).suffix.lower()
    depth=p.get('bit_depth',32 if suffix=='.exr' else 16)
    if type(depth) is not int or depth not in ({16,32} if suffix=='.exr' else {8,16}):
        raise ValueError('PNG accepts 8/16-bit; EXR accepts 16/32-bit')
    isolate=p.get('isolate',True)
    if type(isolate) is not bool:
        raise ValueError('isolate must be boolean')
    layer=bake_layer(value.data,p.get('uv_layer'))
    faces=[f for f in value.data.polygons if f.material_index<len(value.material_slots)
           and value.material_slots[f.material_index].material==material]
    if not faces:
        raise ValueError('Source material needs faces on the target mesh')
    for face in faces:
        for index in face.loop_indices:
            uv=layer.data[index].uv
            if any(not np.isfinite(c) or not 0<=c<=1 for c in uv):
                raise ValueError('Bake UVs must form a single 0..1 atlas; keep tiled shader UVs separate')
    return value,material,spec,layer,resolution,samples,margin,depth,isolate


def write(image, path, depth, role):
    if path.suffix.lower()=='.png':
        write_png(image,path,depth,'lightmap' if role=='color' else 'shader')
        return 'sRGB' if role=='color' else 'Non-Color'
    output=bpy.data.scenes.new('CAVI Channel Output')
    try:
        settings=output.render.image_settings
        settings.file_format='OPEN_EXR'
        settings.color_mode='RGB'
        settings.color_depth=str(depth)
        settings.exr_codec='ZIP'
        image.save_render(str(path),scene=output)
        return image.colorspace_settings.name
    finally:
        bpy.data.scenes.remove(output)


def bake(p):
    with preflight():
        value,source,spec,layer,resolution,samples,margin,depth,isolate=validate(p)
    scene=bpy.context.scene
    saved=state(scene)
    clamps=(scene.cycles.sample_clamp_direct,scene.cycles.sample_clamp_indirect)
    bake_type=scene.cycles.bake_type
    bindings=capture([value])
    selection=list(bpy.context.selected_objects)
    active=bpy.context.view_layer.objects.active
    active_slot=value.active_material_index
    visibility=[(o,o.hide_render,o.hide_viewport,o.hide_get()) for o in scene.objects]
    uv_active=value.data.uv_layers.active_index
    uv_render=[u.active_render for u in value.data.uv_layers]
    material=dummy=image=discard=None
    groups=[]
    with output_file(p['path'],{'.png','.exr'}) as path:
        try:
            image=bpy.data.images.new('CAVI Shader Channel',resolution,resolution,alpha=False,
                                      float_buffer=True,is_data=spec.get('role','data')=='data')
            material,groups,_=clone_graph(source)
            sign=route(material,spec,image)
            # Other material faces must not write into this channel's atlas.
            dummy=bpy.data.materials.new('CAVI Excluded Channel Faces')
            dummy.use_nodes=True
            discard=bpy.data.images.new('CAVI Excluded Channel Pixels',1,1,float_buffer=True)
            target=dummy.node_tree.nodes.new('ShaderNodeTexImage')
            target.image=discard
            dummy.node_tree.nodes.active=target
            for slot in value.material_slots:
                selected=slot.material==source
                slot.link='OBJECT'
                slot.material=material if selected else dummy
            for other,hidden,_,_ in visibility:
                if other==value:
                    other.hide_render=False
                    other.hide_viewport=False
                    other.hide_set(False)
                elif isolate and other.type not in {'LIGHT','LIGHT_PROBE','LIGHTPROBE'}:
                    other.hide_render=True
                else:
                    other.hide_render=hidden
            for other in list(bpy.context.selected_objects):
                other.select_set(False)
            value.select_set(True)
            bpy.context.view_layer.objects.active=value
            bpy.context.view_layer.update()
            scene.render.engine='CYCLES'
            scene.cycles.device='CPU'
            scene.cycles.samples=samples
            scene.cycles.use_denoising=False
            scene.cycles.sample_clamp_direct=scene.cycles.sample_clamp_indirect=0
            settings=scene.render.bake
            settings.use_selected_to_active=False
            settings.use_clear=True
            settings.use_cage=False
            settings.target='IMAGE_TEXTURES'
            settings.margin=margin
            settings.margin_type='EXTEND'
            pixels=np.empty(resolution*resolution*4,dtype=np.float32)
            negative=np.empty_like(pixels)
            for factor,buffer in [(1,pixels),(-1,negative)]:
                sign.default_value=factor
                bpy.context.view_layer.update()
                result=bpy.ops.object.bake(type='EMIT',uv_layer=layer.name)
                if 'FINISHED' not in result:
                    raise RuntimeError('Shader channel bake did not finish')
                image.pixels.foreach_get(buffer)
            np.subtract(pixels,negative,out=pixels)
            rgba=pixels.reshape(-1,4)
            rgba[:,3]=1
            rgb=rgba[:,:3]
            if not np.isfinite(rgb).all():
                raise ValueError('Source produced nonfinite channel samples')
            minimum,maximum=float(rgb.min()),float(rgb.max())
            if path.suffix.lower()=='.png' and (minimum<0 or maximum>1):
                raise ValueError('Signed/HDR channel samples require EXR; PNG would clip them')
            if path.suffix.lower()=='.exr' and depth==16 and max(abs(minimum),abs(maximum))>65504:
                raise ValueError('Channel exceeds half-float range; use 32-bit EXR')
            image.pixels.foreach_set(pixels)
            image.update()
            color_space=write(image,path,depth,spec.get('role','data'))
            receipt={'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path),
                'map':'shader','resolution':resolution,'samples':samples,'margin':margin,
                'bit_depth':depth,'color_space':color_space,'normal_channels':None,
                'cage_extrusion':0,'max_ray_distance':0,'normal_space':None,
                'uv_layer':layer.name,'low':value.name,'high':[],
                'selected_to_active':False,'isolate':isolate,
                'source':{**spec,'group_path':spec.get('group_path',[]),
                    'direction':spec.get('direction','OUTPUT'),'role':spec.get('role','data'),
                    'channels':['R','G','B'],'minimum':minimum,'maximum':maximum}}
        finally:
            restore_bindings(bindings)
            value.active_material_index=active_slot
            value.data.uv_layers.active_index=uv_active
            for uv,flag in zip(value.data.uv_layers,uv_render,strict=True):
                if uv.active_render!=flag:
                    uv.active_render=flag
            restore(scene,saved)
            scene.cycles.bake_type=bake_type
            scene.cycles.sample_clamp_direct,scene.cycles.sample_clamp_indirect=clamps
            for other,render,viewport,hidden in visibility:
                other.hide_render,other.hide_viewport=render,viewport
                other.hide_set(hidden)
            for other in list(bpy.context.selected_objects):
                other.select_set(False)
            for other in selection:
                other.select_set(True)
            bpy.context.view_layer.objects.active=active
            dispose_graph(material,groups)
            if dummy is not None:
                bpy.data.materials.remove(dummy)
            for item in [image,discard]:
                if item is not None:
                    bpy.data.images.remove(item)
        return receipt

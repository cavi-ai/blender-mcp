"""Persistent cameras, lights, managed world nodes and production scene rendering."""

import hashlib
import json
import math
import time

import bpy
from mathutils import Vector

from .blender_bridge import info, obj, output_file, vector
from .blender_images import packed_snapshot
from .blender_rigging import label

WORLD_TAG = 'cavi_managed_world'


def environment_image(path, workspace, existing=None):
    return packed_snapshot(path, workspace, existing, tag='cavi_world_source_sha256')


def scalar(value, minimum=0, maximum=math.inf):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not minimum <= value <= maximum):
        raise ValueError('Expected a finite value in the native property range')
    return value


def look(location, target):
    location, target = Vector(vector(location)), Vector(vector(target))
    direction = target-location
    if direction.length < 1e-6:
        raise ValueError('Camera/light target must differ from its location')
    return location, direction.to_track_quat('-Z', 'Y').to_euler()


def definition_object(name, kind, factory):
    name = label(name)
    value = bpy.data.objects.get(name)
    if value is not None:
        if value.type != kind:
            raise ValueError(f'{name} exists with a different object type')
        if value.data.users > 1:
            value.data = value.data.copy()
    else:
        value = bpy.data.objects.new(name, factory(name))
        bpy.context.scene.collection.objects.link(value)
    return value


def camera(spec):
    location, rotation = look(spec['location'], spec['target'])
    if not 0 < spec['clip_start'] < spec['clip_end']:
        raise ValueError('Camera requires 0 < clip_start < clip_end')
    for field, key in (('lens', 'focal_length_mm'), ('sensor_width', 'sensor_width_mm'),
                       ('ortho_scale', 'ortho_scale'), ('clip_start', 'clip_start'),
                       ('clip_end', 'clip_end')):
        prop = bpy.types.Camera.bl_rna.properties[field]
        scalar(spec[key], prop.hard_min, prop.hard_max)
    value = definition_object(spec['name'], 'CAMERA', bpy.data.cameras.new)
    value.rotation_mode = 'XYZ'
    value.location, value.rotation_euler = location, rotation
    data = value.data
    data.type = {'perspective': 'PERSP', 'orthographic': 'ORTHO'}[spec['projection']]
    data.lens, data.sensor_width = spec['focal_length_mm'], spec['sensor_width_mm']
    data.ortho_scale = spec['ortho_scale']
    data.clip_start, data.clip_end = spec['clip_start'], spec['clip_end']
    data.shift_x, data.shift_y = spec['shift']
    data.dof.use_dof = spec['depth_of_field']
    data.dof.focus_object = None
    data.dof.focus_distance, data.dof.aperture_fstop = spec['focus_distance'], spec['fstop']
    bpy.context.scene.camera = value
    bpy.context.view_layer.update()
    return {**info(value), 'camera': {'projection': data.type, 'focal_length_mm': data.lens,
        'sensor_width_mm': data.sensor_width, 'clip': [data.clip_start, data.clip_end],
        'shift': [data.shift_x, data.shift_y], 'depth_of_field': data.dof.use_dof,
        'focus_distance': data.dof.focus_distance, 'fstop': data.dof.aperture_fstop}}


def light(spec):
    location = vector(spec['location'])
    rotation = look(location, spec['target'])[1] if spec['target'] is not None else None
    scalar(spec['energy'])
    color = vector(spec['color'])
    for component in color:
        scalar(component, 0, 1)
    value = definition_object(spec['name'], 'LIGHT',
                              lambda name: bpy.data.lights.new(name, spec['type']))
    value.location = location
    if rotation is not None:
        value.rotation_mode, value.rotation_euler = 'XYZ', rotation
    data = value.data
    data.type, data.energy, data.color = spec['type'], spec['energy'], color
    if data.type == 'AREA':
        data.shape, data.size = spec['shape'], spec['size']
        if data.shape in {'RECTANGLE', 'ELLIPSE'}:
            data.size_y = spec['size_y']
    elif data.type == 'SUN':
        data.angle = math.radians(spec['angle_degrees'])
    else:
        data.shadow_soft_size = spec['radius']
        if data.type == 'SPOT':
            data.spot_size, data.spot_blend = math.radians(spec['spot_size_degrees']), spec['spot_blend']
    return {**info(value), 'light': {'type': data.type, 'energy': data.energy,
                                    'color': list(data.color)}}


def world(spec, workspace):
    name = label(spec['name'])
    color = vector(spec['color'])
    for component in color:
        scalar(component)
    scalar(spec['strength'])
    rotation = [math.radians(v) for v in vector(spec['rotation_degrees'])]
    image, source = None, None
    value = bpy.data.worlds.get(name)
    if value is not None and not value.get(WORLD_TAG):
        raise ValueError('World name belongs to an authored graph; choose a new managed world name')
    if spec['hdri'] is not None:
        path = (workspace / spec['hdri']).resolve(strict=True)
        if (not path.is_relative_to(workspace) or not path.is_file()
                or path.suffix.lower() not in {'.exr', '.hdr', '.png', '.tif', '.tiff', '.jpg'}):
            raise ValueError('HDRI must be a supported workspace image')
        previous = value.node_tree.nodes.get('CaviEnvironment') if value else None
        image, fingerprint = environment_image(path, workspace,
                                               previous.image if previous else None)
        source = {'path': path.relative_to(workspace).as_posix(), 'sha256': fingerprint}
    if value is None:
        value = bpy.data.worlds.new(name)
        value.use_nodes = True
        nodes = value.node_tree.nodes
        nodes.clear()
        for identifier, kind in (('Background', 'ShaderNodeBackground'),
                                  ('Output', 'ShaderNodeOutputWorld'),
                                  ('Environment', 'ShaderNodeTexEnvironment'),
                                  ('Coordinates', 'ShaderNodeTexCoord'),
                                  ('Mapping', 'ShaderNodeMapping')):
            node = nodes.new(kind)
            node.name = 'Cavi' + identifier
        links = value.node_tree.links
        links.new(nodes['CaviBackground'].outputs['Background'], nodes['CaviOutput'].inputs['Surface'])
        links.new(nodes['CaviCoordinates'].outputs['Generated'], nodes['CaviMapping'].inputs['Vector'])
        links.new(nodes['CaviMapping'].outputs['Vector'], nodes['CaviEnvironment'].inputs['Vector'])
        value[WORLD_TAG] = True
    nodes, links = value.node_tree.nodes, value.node_tree.links
    expected = {'CaviBackground', 'CaviOutput', 'CaviEnvironment', 'CaviCoordinates', 'CaviMapping'}
    if not expected <= set(nodes.keys()):
        raise ValueError('Managed world nodes changed; inspect the graph before editing')
    value.use_nodes = True
    nodes['CaviOutput'].is_active_output = True
    background = nodes['CaviBackground']
    for link in list(background.inputs['Color'].links):
        links.remove(link)
    background.inputs['Color'].default_value = (*color, 1)
    background.inputs['Strength'].default_value = spec['strength']
    nodes['CaviMapping'].inputs['Rotation'].default_value = rotation
    nodes['CaviEnvironment'].image = image
    if image is not None:
        links.new(nodes['CaviEnvironment'].outputs['Color'], background.inputs['Color'])
    bpy.context.scene.world = value
    return {'world': value.name, 'strength': float(background.inputs['Strength'].default_value),
            'source': source, 'rotation_degrees': spec['rotation_degrees'],
            'source_color_space': image.colorspace_settings.name if image else None}


def render(spec):
    width, height, samples = spec['width'], spec['height'], spec['samples']
    if any(type(v) is not int or v < 1 for v in (width, height, samples, spec['max_pixels'])):
        raise ValueError('Render dimensions, samples and max_pixels must be positive integers')
    if width*height > spec['max_pixels']:
        raise ValueError('Render dimensions exceed max_pixels')
    suffixes = {'png': {'.png'}, 'exr': {'.exr'}, 'tiff': {'.tif', '.tiff'}}
    depths = {'png': {'8', '16'}, 'exr': {'16', '32'}, 'tiff': {'8', '16'}}
    if spec['bit_depth'] not in depths[spec['file_format']]:
        raise ValueError('Bit depth does not match the output format')
    camera_object = obj(spec['camera'])
    if camera_object.type != 'CAMERA':
        raise ValueError('Render camera must name a camera object')
    scene = bpy.context.scene
    if spec['engine'] == 'cycles' and spec['device'] == 'GPU':
        preferences = bpy.context.preferences.addons['cycles'].preferences
        preferences.refresh_devices()
        if not any(d.use and d.type != 'CPU' for d in preferences.devices):
            raise ValueError('No enabled Cycles GPU; configure a backend/device or select CPU')
    started = time.monotonic()
    with output_file(spec['path'], suffixes[spec['file_format']]) as path:
        scene.camera = camera_object
        if spec['frame'] is not None:
            scene.frame_set(spec['frame'])
        if spec['engine'] == 'cycles':
            scene.render.engine = 'CYCLES'
            scene.cycles.device, scene.cycles.samples = spec['device'], samples
            scene.cycles.use_denoising = spec['denoise']
            scene.cycles.time_limit = spec['cycles_time_limit']
        else:
            try:
                scene.render.engine = 'BLENDER_EEVEE'
            except TypeError:
                scene.render.engine = 'BLENDER_EEVEE_NEXT'
            scene.eevee.taa_render_samples = samples
        output = scene.render
        output.resolution_x, output.resolution_y, output.resolution_percentage = width, height, 100
        output.threads_mode, output.threads = 'FIXED', spec['threads']
        output.film_transparent = spec['transparent']
        output.image_settings.file_format = {'png': 'PNG', 'exr': 'OPEN_EXR', 'tiff': 'TIFF'}[
            spec['file_format']]
        output.image_settings.color_mode, output.image_settings.color_depth = 'RGBA', spec['bit_depth']
        output.use_file_extension = True
        output.filepath = str(path)
        scene.view_settings.view_transform = spec['view_transform']
        scene.view_settings.exposure, scene.view_settings.gamma = spec['exposure'], spec['gamma']
        scene['cavi_render_definition'] = json.dumps(spec, sort_keys=True)
        def projection():
            from .blender_camera_ray import snapshot

            try:
                return snapshot(camera_object,[width,height])
            except (ValueError,TypeError,RuntimeError) as exc:
                return {'available':False,'reason':str(exc)}

        camera_projection=projection()
        from .blender_scene_geometry import capture

        geometry_identity=capture()
        result = bpy.ops.render.render(write_still=True)
        if 'FINISHED' not in result:
            raise RuntimeError('Scene render did not finish')
        after=projection()
        if camera_projection.get('available') and after != camera_projection:
            camera_projection={'available':False,'reason':'Camera projection changed during render'}
        after_geometry=capture()
        if geometry_identity.get('available') and after_geometry.get('sha256')!=geometry_identity['sha256']:
            geometry_identity={'available':False,'reason':'Scene geometry changed during render'}
    elapsed = time.monotonic()-started
    with path.open('rb') as stream:
        sha256=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'engine': scene.render.engine,
            'width': width, 'height': height, 'bit_depth': int(spec['bit_depth']),
            'samples_requested': samples, 'elapsed_seconds': elapsed,
            'cycles_sampling_may_have_hit_time_limit': spec['engine'] == 'cycles'
            and spec['cycles_time_limit'] > 0 and elapsed >= spec['cycles_time_limit'],
            'camera': camera_object.name, 'world': scene.world.name if scene.world else None,
            'sha256':sha256,'camera_projection':camera_projection,'geometry_identity':geometry_identity}


def author(p, workspace):
    action, spec = p.get('action'), p.get('definition')
    if not isinstance(spec, dict):
        raise TypeError('definition must be an object')
    if action == 'camera':
        return camera(spec)
    if action == 'light':
        return light(spec)
    if action == 'world':
        return world(spec, workspace)
    if action == 'render':
        return render(spec)
    raise ValueError('Unknown scene authoring action')

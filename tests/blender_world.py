"""Native HDRI snapshot fidelity, dirty-cache isolation and packed-world persistence."""

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp.blender_scene import world

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder).resolve();source=root/'environment.exr'
    image=bpy.data.images.new('Environment source',width=8,height=4,float_buffer=True)
    image.pixels.foreach_set([v for i in range(32) for v in (i/31,.123456,.234567,1)])
    scene=bpy.context.scene
    scene.render.image_settings.file_format='OPEN_EXR'
    scene.render.image_settings.color_depth='32'
    image.save_render(str(source),scene=scene)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    cached=bpy.data.images.load(str(source),check_existing=False)
    cached.pixels[0]=.98765;cached.update();assert cached.is_dirty
    spec={'name':'Managed world','color':[.05,.05,.05],'strength':.4,
          'hdri':source.name,'rotation_degrees':[0,0,35]}
    report=world(spec,root)
    environment=scene.world.node_tree.nodes['CaviEnvironment'].image
    assert environment != cached
    assert hashlib.sha256(environment.packed_file.data).hexdigest()==digest==report['source']['sha256']
    scene.world.use_nodes=False
    world(spec,root)
    assert scene.world.use_nodes
    assert scene.world.node_tree.nodes['CaviEnvironment'].image==environment
    assert not list(root.glob('.cavi-world-*'))
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'world.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(root/'world.blend'))
    assert bpy.context.scene.world.name=='Managed world'
    environment=bpy.context.scene.world.node_tree.nodes['CaviEnvironment'].image
    assert hashlib.sha256(environment.packed_file.data).hexdigest()==digest
    rotation=bpy.context.scene.world.node_tree.nodes['CaviMapping'].inputs['Rotation'].default_value.z
    assert abs(rotation-math.radians(35))<1e-6
    print(json.dumps({'packed_source_matches':True,'dirty_cache_preserved':True,
                      'managed_world_reopened':True}))

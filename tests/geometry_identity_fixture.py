"""Observe actual 16-bit baseline/candidate pixels using Blender's image decoder."""
import json
import os
import runpy
from pathlib import Path

import bpy

root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
runpy.run_path(str(Path(__file__).with_name('scene_pick_fixture.py')))
references=json.loads((root/'references.json').read_text())
samples={}


@bpy.app.handlers.persistent
def measure(*_):
    for name in ('identity-baseline','identity-moved'):
        path=root/(name+'.png')
        if name in samples or not path.exists():
            continue
        image=bpy.data.images.load(str(path),check_existing=False)
        try:
            width,height=image.size
            x,y=(round(v) for v in references['Foreground']['pixel'])
            offset=((height-1-y)*width+x)*4
            samples[name]={'bit_depth':path.read_bytes()[24],'rgba':list(image.pixels[offset:offset+4])}
        finally:
            bpy.data.images.remove(image)
    (root/'identity-samples.json').write_text(json.dumps(samples))


bpy.app.handlers.save_post.append(measure)


@bpy.app.handlers.persistent
def drift_after_render(*_):
    if Path(bpy.context.scene.render.filepath).stem=='identity-drift':
        bpy.data.objects['Foreground'].location.x=.25
        bpy.app.handlers.render_post.remove(drift_after_render)


bpy.app.handlers.render_post.append(drift_after_render)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'),check_existing=False)

"""Native precision, shared images, ownership rollback and saved authored controls."""

import hashlib
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_asset_library import ids
from cavi_blender_mcp.blender_materials import CONFIG_TAG
from cavi_blender_mcp.blender_scene import environment_image

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)/'workspace'
    root.mkdir()
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('shader_texture_fixture.py')))
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'baseline.blend'))
    context = bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    common = {'material_name': 'ArtistFinish', 'group_path': ['Finish Controls', 'Inner Layer']}
    tree = bpy.data.node_groups['ArtistSurface']
    texture, sibling = tree.nodes['Pattern'], tree.nodes['Other Pattern']
    previous = texture.image
    old_bytes = bytes(previous.packed_file.data)
    old_color, old_alpha = previous.colorspace_settings.name, previous.alpha_mode
    image_settings = texture.interpolation, texture.projection, texture.projection_blend, texture.extension, texture.label
    source = (root/'finish.png').read_bytes()
    assert source[24] == 16
    args = {**common, 'node': 'Pattern'}
    before = shader.inspect(args)
    before_ids = ids()
    assert not bpy.data.is_dirty
    previous.pixels[0] = .789123
    artist_pixels = list(previous.pixels)
    outside = Path(folder)/'outside.png'
    outside.write_bytes(source)
    (root/'escape.png').symlink_to(outside)
    for name in ['../outside.png', 'escape.png']:
        try:
            shader.set_image({**args, 'image': {'path': name, 'color_space': 'Non-Color'}}, root)
        except ValueError as exc:
            assert 'inside the workspace' in str(exc), exc
        else:
            raise AssertionError('External image was accepted')
    assert ids() == before_ids and texture.image == previous
    configs = {name: bpy.data.materials[name][CONFIG_TAG] for name in ['ManagedA', 'ManagedB']}
    image = {'path': 'finish.png', 'color_space': 'Non-Color', 'alpha_mode': 'CHANNEL_PACKED'}
    with patch.object(shader, 'node_report', side_effect=RuntimeError('receipt failed')):
        try:
            shader.set_image({**args, 'image': image}, root)
        except RuntimeError as exc:
            assert str(exc) == 'receipt failed'
        else:
            raise AssertionError('Injected receipt failure succeeded')
    assert ids() == before_ids and texture.image == previous
    assert shader.inspect(args) == before
    assert all(bpy.data.materials[name][CONFIG_TAG] == config for name, config in configs.items())
    assert all(shader.PROVENANCE_TAG not in bpy.data.materials[name] for name in configs)
    result = shader.set_image({**args, 'image': image}, root)
    assert texture.image != previous and sibling.image == previous
    assert bytes(texture.image.packed_file.data) == source
    pixel = texture.image.pixels[0]
    assert abs(pixel*255-round(pixel*255)) > .001, pixel
    for name, config in configs.items():
        assert CONFIG_TAG not in bpy.data.materials[name]
        assert bpy.data.materials[name][shader.PROVENANCE_TAG] == config
    assert image_settings == (texture.interpolation, texture.projection, texture.projection_blend, texture.extension, texture.label)
    assert context == (bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    prior_image = texture.image
    (root/'finish.png').write_bytes((root/'old.png').read_bytes())
    revised = shader.set_image({**args, 'image': image}, root)
    assert revised['changed_image'] and texture.image != prior_image
    assert bytes(prior_image.packed_file.data) == source
    assert bytes(texture.image.packed_file.data) == (root/'finish.png').read_bytes()
    assert not shader.set_image({**args, 'image': image}, root)['changed_image']
    hdr = shader.set_image({**args, 'image': {**image, 'path': 'finish.exr'}}, root)
    samples = list(texture.image.pixels[:4])
    assert texture.image.is_float and samples[1] < 0 and samples[2] > 1, samples
    assert hashlib.sha256(texture.image.packed_file.data).hexdigest() == hdr['image_source']['sha256']
    assert previous.colorspace_settings.name == old_color and previous.alpha_mode == old_alpha
    assert list(previous.pixels) == artist_pixels
    assert bytes(previous.packed_file.data) == old_bytes and previous['artist_note'] == 'retain'
    value = tree.nodes['Glaze Weight']
    tint = tree.nodes['Glow Tint']
    shader.set_inputs({**common, 'node': value.name, 'outputs': {value.outputs[0].identifier: .6}})
    shader.set_inputs({**common, 'node': tint.name, 'outputs': {tint.outputs[0].identifier: [.1, .2, .4, 1.]}})
    native = shader.inspect(args)
    assert native['links'] == before['links']
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'authored.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(root/'authored.blend'))
    assert shader.inspect(args) == native
    tree = bpy.data.node_groups['ArtistSurface']
    assert abs(tree.nodes['Glaze Weight'].outputs[0].default_value-.6) < 1e-6
    assert abs(tree.nodes['Glow Tint'].outputs[0].default_value[2]-.4) < 1e-6
    assert tree.nodes['Pattern'].image != tree.nodes['Other Pattern'].image
    # The world adapter retains its public provenance key through the shared loader.
    world_image, fingerprint = environment_image(root/'finish.exr', root)
    assert world_image['cavi_world_source_sha256'] == fingerprint
    assert environment_image(root/'finish.exr', root, world_image)[0] == world_image
    bpy.data.images.remove(world_image)
    print(json.dumps({'native_shader_textures': 'passed', 'png_bit_depth': 16,
        'png_retains_non_byte_samples': True, 'exr_float_hdr_samples': samples,
        'source_bytes_packed_exactly': True, 'replaced_source_not_cached': True,
        'failed_receipt_restores_ids_binding_and_tags': True, 'other_image_users_preserved': True, 'unsaved_image_pixels_preserved': True,
        'existing_external_and_symlink_sources_rejected': True,
        'texture_settings_and_context_preserved': True, 'value_rgb_and_image_survive_reopen': True,
        'world_adapter_snapshot_reuse': True}))

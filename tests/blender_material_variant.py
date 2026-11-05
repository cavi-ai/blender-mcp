"""Material graph copies preserve sharing boundaries and reverse failed bindings."""
import hashlib
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_asset_library import ids

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    os.environ['CAVI_BLENDER_WORKSPACE']=folder
    bridge._workspace=root
    runpy.run_path(str(Path(__file__).with_name('material_variant_fixture.py')))
    shader.set_image({'material_name':'ArtistFinish','group_path':['Finish Controls','Inner Layer'],
        'node':'Pattern','image':{'path':'glaze.<UDIM>.png','tiles':[1001,1002,1011,1012],
            'color_space':'Non-Color'}},root)
    source=bpy.data.materials['ArtistFinish']
    surface,second,peer=[bpy.data.objects[n] for n in ['TileGrid','SecondTarget','FinishPeer']]
    outer=source.node_tree.nodes['Finish Controls'].node_tree
    inner=outer.nodes['Inner Layer'].node_tree
    image=inner.nodes['Pattern'].image
    packed=[hashlib.sha256(p.packed_file.data).hexdigest() for p in image.packed_files]
    def context():
        return {'objects':set(bpy.data.objects),'mesh':surface.data,'vertices':[tuple(v.co) for v in surface.data.vertices],
            'selected':set(bpy.context.selected_objects),'active':bpy.context.view_layer.objects.active,
            'file':bpy.data.filepath,'frame':bpy.context.scene.frame_current,
            'data_slots':list(surface.data.materials)}
    def slots():
        return {o.name:[(s.link,s.material) for s in o.material_slots] for o in [surface,second,peer]}
    before=context()
    original_slots=slots()
    state=bridge.dispatch('session_control',{'action':'inspect'})
    lease=bridge.dispatch('session_control',{'action':'claim','owner':'finish-author',
        'expected_project':state['project_id']})['lease_id']
    def copy(name, **options):
        return bridge.dispatch('owned_edit',{'operation':'make_material_unique','params':{
            'material_name':name,'names':[surface.name,second.name],'slot':0,'link_mode':'OBJECT',
            'lease_id':lease,**options}})
    result=copy('VariantFinish')
    variant=bpy.data.materials['VariantFinish']
    outer_copy=variant.node_tree.nodes['Finish Controls'].node_tree
    inner_copy=outer_copy.nodes['Inner Layer'].node_tree
    assert source.node_tree!=variant.node_tree and outer!=outer_copy and inner!=inner_copy
    assert variant.node_tree.nodes['Reused Controls'].node_tree==outer_copy
    assert inner_copy.nodes['Pattern'].image==image
    assert inner_copy.animation_data.action==inner.animation_data.action
    assert variant.node_tree.nodes['Scene Anchor'].object==surface
    assert source['artist_note']==variant['artist_note']=='retain'
    assert source.use_fake_user and not variant.use_fake_user
    assert result['material_copy']['source']==source.name and result['material_copy']['node_group_count']==2
    assert all(o.material_slots[0].link=='OBJECT' and o.material_slots[0].material==variant for o in [surface,second])
    assert peer.material_slots[0].material==bpy.data.materials['OtherFinish'] and context()==before
    shader.set_inputs({'material_name':variant.name,'group_path':['Finish Controls','Inner Layer'],
        'node':'Variant Gain','outputs':{'Value':.25}})
    assert inner_copy.nodes['Variant Gain'].outputs[0].default_value==.25
    assert inner.nodes['Variant Gain'].outputs[0].default_value==1
    assert [hashlib.sha256(p.packed_file.data).hexdigest() for p in image.packed_files]==packed
    from cavi_blender_mcp import blender_material_variants as variants
    stable_ids,stable_slots=ids(),slots()
    with patch.object(variants,'inspect',side_effect=RuntimeError('receipt failure')):
        try:
            copy('FailedFinish')
        except RuntimeError as exc:
            assert str(exc)=='receipt failure'
        else:
            raise AssertionError('Expected failed material receipt')
    assert ids()==stable_ids and slots()==stable_slots and context()==before
    real_bind=variants.bind
    def partial(values, material, slot, modes):
        real_bind(values[:1],material,slot,modes)
        raise RuntimeError('partial binding')
    with patch.object(variants,'bind',partial):
        try:
            copy('PartialFinish')
        except RuntimeError as exc:
            assert str(exc)=='partial binding'
        else:
            raise AssertionError('Expected failed partial binding')
    assert ids()==stable_ids and slots()==stable_slots and context()==before
    # A clean source binding is needed for explicit DATA and mixed-source rejection checks.
    surface.material_slots[0].link=second.material_slots[0].link='DATA'
    for options in [{'link_mode':'DATA'},{'names':[surface.name,peer.name]},{'slot':3}]:
        prior_ids,prior_slots=ids(),slots()
        try:
            copy('RejectedFinish',**options)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid material variant was accepted')
        assert ids()==prior_ids and slots()==prior_slots
    surface.material_slots[0].link='OBJECT'
    surface.material_slots[0].material=variant
    unique=surface.copy()
    unique.name,unique.hide_render='UniqueData',True
    unique.data=surface.data.copy()
    bpy.context.scene.collection.objects.link(unique)
    unique.material_slots[0].link='DATA'
    data_result=copy('DataVariant',names=[unique.name],link_mode='DATA')
    assert unique.data.materials[0]==bpy.data.materials[data_result['material']]
    assert surface.data.materials[0]==source
    plain=bpy.data.materials.new('PlainSource')
    plain.diffuse_color=(.2,.3,.4,.7)
    unique.data.materials[0]=plain
    plain_result=copy('PlainVariant',names=[unique.name])
    assert plain_result['nodes']==shader.inspect({'material_name':plain.name})['nodes']
    assert plain_result['material_copy']['node_group_count']==0
    assert tuple(bpy.data.materials['PlainVariant'].diffuse_color)==tuple(plain.diffuse_color)
    path=root/'variant.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    saved=bpy.data.materials['VariantFinish'].node_tree.nodes['Finish Controls'].node_tree
    assert saved.nodes['Inner Layer'].node_tree.nodes['Variant Gain'].outputs[0].default_value==.25
    assert bpy.data.node_groups['ArtistSurface'].nodes['Variant Gain'].outputs[0].default_value==1
    print(json.dumps({'native_material_variant':'passed','nested_groups_independent':True,
        'shared_group_identity_retained_within_variant':True,'image_action_and_scene_references_retained':True,
        'source_and_peer_finish_unchanged':True,'failed_copy_bindings_and_ids_restored':True,
        'geometry_and_context_unchanged':True,'partial_binding_rolled_back':True,
        'data_binding_and_plain_material_checked':True,'save_reopen_checked':True}))

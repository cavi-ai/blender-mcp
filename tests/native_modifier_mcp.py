"""Inspect, adjust and remove exact modifiers without rebuilding source geometry."""
import copy
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main, verify_source_identity


async def exercise(root,env,parameters=None):
    scoped=parameters is not None
    parameters=parameters or StdioServerParameters(command=sys.executable,args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(parameters) as streams,ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool,**args):
            result=await client.call_tool(tool,args)
            assert not result.is_error,result
            return result.structured_content

        state=await call('scene_info',limit=1)
        assert Path(state['workspace']).resolve()==root.resolve() and Path(state['file']).resolve()==root/'initial.blend'
        before=json.loads((root/'modifier-audit.json').read_text())
        hero=await call('scene_info',name='Hero')
        mods={m['name']:m for m in hero['modifiers']}
        assert mods['HeroRound']['settings']['segments']==3,mods
        assert mods['HeroRound']['control_schema']['segments']['type']=='INT',mods
        unowned=await client.call_tool('mesh_edit',{'action':'modifier_update','name':'Hero',
            'modifier_name':'HeroRound','amount':.12})
        assert unowned.is_error,unowned
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='modifier-native',expected_project=owner['project_id']))['lease_id']

        async def change(name,modifier,amount):
            return await call('mesh_edit',action='modifier_update',name=name,
                              modifier_name=modifier,amount=amount,lease_id=lease)

        async def reject(action,**args):
            stack=(await call('scene_info',name=args['name']))['modifiers']
            result=await client.call_tool('mesh_edit',{'action':action,'lease_id':lease,**args})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert (await call('scene_info',name=args['name']))['modifiers']==stack

        for name,modifier,amount,field,expected in [('Hero','HeroRound',.12,'width',.12),
            ('Hero','FinishReduction',.6,'ratio',.6),('Subdiv','Subdiv',2,'levels',2),
            ('Voxel','Voxel',.1,'voxel_size',.1)]:
            result=await change(name,modifier,amount)
            row=next(m for m in result['modifiers'] if m['name']==modifier)
            assert abs(row['settings'][field]-expected)<1e-6,row
        patched=await call('mesh_edit',action='modifier_update',name='Hero',modifier_name='HeroRound',
            modifier_settings={'segments':5,'profile':.73,'show_render':False},lease_id=lease)
        row=next(m for m in patched['modifiers'] if m['name']=='HeroRound')
        assert row['settings']['segments']==5 and abs(row['settings']['profile']-.73)<1e-6
        assert abs(row['settings']['width']-.12)<1e-6 and row['show_render'] is False
        patched=await call('mesh_edit',action='modifier_update',name='Hero',modifier_name='HeroRound',
            modifier_settings={'offset_type':'PERCENT','width_pct':37.5},lease_id=lease)
        row=next(m for m in patched['modifiers'] if m['name']=='HeroRound')
        assert row['settings']['offset_type']=='PERCENT' and abs(row['settings']['width_pct']-37.5)<1e-6
        patched=await call('mesh_edit',action='modifier_update',name='Subdiv',modifier_name='Subdiv',
            modifier_settings={'levels':4,'render_levels':6},lease_id=lease)
        row=patched['modifiers'][0]
        assert row['settings']['levels']==4 and row['settings']['render_levels']==6
        patched=await call('mesh_edit',action='modifier_update',name='Voxel',modifier_name='Voxel',
            modifier_settings={'mode':'SMOOTH','octree_depth':5},lease_id=lease)
        assert patched['modifiers'][0]['settings']['mode']=='SMOOTH'
        patched=await call('mesh_edit',action='modifier_update',name='Unknown',modifier_name='Procedural',
            modifier_settings={'show_viewport':False,'show_render':False},lease_id=lease)
        assert patched['modifiers'][0]['show_viewport'] is False and patched['modifiers'][0]['show_render'] is False
        await reject('modifier_update',name='Unknown',modifier_name='Procedural',modifier_settings={'show_render':True})
        await reject('modifier_update',name='Voxel',modifier_name='Voxel',modifier_settings={'mode':'VOXEL','voxel_size':0})
        for settings in ({},{'segments':2.5},{'segments':True},{'profile':2},
                         {'segments':8,'profile':-1},{'show_render':1},{'offset_type':'unknown'},{'missing':.1}):
            await reject('modifier_update',name='Hero',modifier_name='HeroRound',modifier_settings=settings)
        for args in [{'name':'Hero','modifier_name':'missing','amount':.1},
                     {'name':'Hero','modifier_name':'Skin','amount':.1},
                     {'name':'Hero','modifier_name':'HeroRound','amount':-1},
                     {'name':'Subdiv','modifier_name':'Subdiv','amount':1.5},
                     {'name':'BudgetGrid','modifier_name':'Subdivision','amount':3}]:
            await reject('modifier_update',**args)
        for name in ('Animated','NlaAnimated','Driven'):
            await reject('modifier_update',name=name,modifier_name='Controlled',amount=.1)
        for name in ('Animated','NlaAnimated','Driven','Referenced'):
            await reject('modifier_remove',name=name,modifier_name='Controlled')
        await call('asset_io',action='save',path='adjusted.blend',lease_id=lease)
        assert json.loads((root/'modifier-audit.json').read_text())==before
        adjusted={name:(await call('scene_info',name=name))['modifiers'] for name in ('Hero','Peer','Subdiv','Voxel','Unknown')}
        await call('asset_io',action='open',path='adjusted.blend',lease_id=lease)
        for name,stack in adjusted.items():
            assert (await call('scene_info',name=name))['modifiers']==stack,name
        peer=await call('scene_info',name='Peer')
        assert abs(next(m for m in peer['modifiers'] if m['name']=='HeroRound')['settings']['width']-.05)<1e-6
        removed=await call('mesh_edit',action='modifier_remove',name='Hero',modifier_name='HeroRound',lease_id=lease)
        assert [m['name'] for m in removed['modifiers']]==['Skin','FinishReduction']
        persisted={name:(await call('scene_info',name=name))['modifiers'] for name in ('Hero','Peer','Subdiv','Voxel','BudgetGrid','Unknown')}
        rejected=await client.call_tool('mesh_edit',{'action':'modifier_remove','name':'Hero',
            'modifier_name':'HeroRound','lease_id':lease})
        assert rejected.is_error and rejected.structured_content['error']['outcome']=='rejected',rejected
        await call('asset_io',action='save',path='finished.blend',lease_id=lease)
        after=json.loads((root/'modifier-audit.json').read_text())
        expected=copy.deepcopy(before)
        expected['Hero']['stack']=[['Skin','ARMATURE'],['FinishReduction','DECIMATE']]
        assert after==expected,(after,expected)
        await call('asset_io',action='open',path='finished.blend',lease_id=lease)
        result=await call('scene_info',name='Hero')
        assert [m['name'] for m in result['modifiers']]==['Skin','FinishReduction']
        assert abs(result['modifiers'][1]['settings']['ratio']-.6)<1e-6
        for name,stack in persisted.items():
            assert (await call('scene_info',name=name))['modifiers']==stack,name
        await call('asset_io',action='save',path='reopened.blend',lease_id=lease)
        assert json.loads((root/'modifier-audit.json').read_text())==after
        await call('session_control',action='release',lease_id=lease)
        await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'source-audits.json').write_text(json.dumps({'before':before,'after':after},indent=2)+'\n')
        return {'modifiers':'passed','scoped_profile':scoped,'adjusted':['BEVEL','DECIMATE','SUBSURF','REMESH'],
                'named_removal':'passed','shared_mesh_and_peer':'preserved','rig_uv_and_shape_data':'preserved',
                'source_selection':'unchanged','save_reopen':'passed','dedicated_source_identity_test':'passed',
                'native_controls':['BOOLEAN','INT','FLOAT','ENUM'],'independent_subdivision':[4,6],
                'atomic_map_rejection':'passed','adjusted_settings_reopen':'passed','visibility_only_disabling':'passed'}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('modifier_fixture.py'))

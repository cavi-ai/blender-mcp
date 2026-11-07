"""Delete owned objects through real MCP and inspect the saved, reopened source."""
import hashlib
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


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
        assert state['source_state']['saved_source']['sha256']==hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        before=json.loads((root/'deletion-audit.json').read_text())
        denied=await client.call_tool('object_edit',{'action':'delete','name':'Draft'})
        assert denied.is_error and any('lease_id' in getattr(i,'text','') for i in denied.content),denied
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='object-delete-native',expected_project=owner['project_id']))['lease_id']
        for name,recursive,reason in [('Hierarchy',False,'children'),('BlockedRoot',True,'Keep'),
                                      ('CrossScene',False,'another scene'),('KitDefinition',False,'instanced'),
                                      ('SceneBound',False,'Scene'),('MetadataBound',False,'Kit')]:
            result=await client.call_tool('object_edit',{'action':'delete','name':name,'recursive':recursive,'lease_id':lease})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert any(reason.lower() in getattr(i,'text','').lower() for i in result.content),result
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        await call('asset_io',action='save',path='checked.blend',lease_id=lease)
        assert json.loads((root/'deletion-audit.json').read_text())==before
        receipts=[]
        for name,recursive,names in [('Draft',False,['Draft']),('Hierarchy',True,
                ['Hierarchy','HierarchyBranch','HierarchyChild','HierarchyGrandchild']),('KitPlacement',False,['KitPlacement']),
                ('CollectionDraft',False,['CollectionDraft'])]:
            result=await call('object_edit',action='delete',name=name,recursive=recursive,lease_id=lease)
            assert result['name']==name and result['deleted']==names and result['count']==len(names),result
            receipts.append(result)
        absent=await client.call_tool('object_edit',{'action':'delete','name':'Draft','lease_id':lease})
        assert absent.is_error and absent.structured_content['error']['outcome']=='rejected',absent
        expected=['BlockedRoot','Control','CrossScene','FreeChild','Keep','KitDefinition','MetadataBound','SceneBound']
        assert sorted(o['name'] for o in (await call('scene_info',limit=1000))['objects'])==expected
        await call('asset_io',action='save',path='deleted.blend',lease_id=lease)
        after=json.loads((root/'deletion-audit.json').read_text())
        assert sorted(after['objects'])==expected and after['active']==before['active']=='Keep'
        assert all(after['objects'][name]==before['objects'][name] for name in expected)
        assert after['scenes']['OtherScene']==before['scenes']['OtherScene']==['CrossScene']
        removed={name for receipt in receipts for name in receipt['deleted']}
        assert after['collections']=={name:[o for o in objects if o not in removed] for name,objects in before['collections'].items()}
        assert after['scene_refs']==before['scene_refs'] and after['collection_refs']==before['collection_refs']
        assert after['materials']==before['materials']
        original,shared=before['meshes']['SharedMesh'],after['meshes']['SharedMesh']
        assert original['users']==10 and shared['users']==6
        assert all(shared[key]==original[key] for key in ['vertices','faces','uv','materials'])
        saved=hashlib.sha256((root/'deleted.blend').read_bytes()).hexdigest()
        await call('asset_io',action='open',path='deleted.blend',lease_id=lease)
        reopened=await call('scene_info',limit=1000)
        assert sorted(o['name'] for o in reopened['objects'])==expected
        assert reopened['source_state']['saved_source']['sha256']==saved
        await call('asset_io',action='save',path='reopened.blend',lease_id=lease)
        assert json.loads((root/'deletion-audit.json').read_text())==after
        await call('session_control',action='release',lease_id=lease)
        evidence=os.environ.get('CAVI_NATIVE_EVIDENCE')
        if evidence:
            (Path(evidence)/'source-audits.json').write_text(json.dumps({'before':before,'after':after},indent=2)+'\n')
        return {'object_deletion':'passed','scoped_profile':scoped,'deleted_objects':7,
            'preflight_rejections':6,'missing_lease':'rejected','missing_object':'rejected',
            'shared_data':'preserved','unrelated_scene':'preserved','saved_reopened':'passed',
            'receipts':receipts,'saved_source_sha256':saved}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('object_delete_fixture.py'))

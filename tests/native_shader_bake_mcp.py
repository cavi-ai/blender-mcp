"""Shader-channel precision and ownership through MCP stdio and native Blender."""
import hashlib
import struct
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


def exr_channel_types(path):
    with path.open('rb') as stream:
        assert stream.read(4)==b'v/1\x01'
        stream.read(4)
        def string():
            value=bytearray()
            while (byte:=stream.read(1))!=b'\0':
                assert byte,'Truncated EXR header'
                value.extend(byte)
            return value.decode()
        while (name:=string()):
            kind=string()
            size=struct.unpack('<I',stream.read(4))[0]
            payload=stream.read(size)
            if name=='channels':
                assert kind=='chlist'
                result={}
                while payload[0]:
                    name,payload=payload.split(b'\0',1)
                    result[name.decode()]=struct.unpack('<i',payload[:4])[0]
                    payload=payload[16:]
                return result
    raise AssertionError('Missing EXR channels')


async def exercise(root, env):
    params=StdioServerParameters(command=sys.executable,args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized=await client.initialize()
        async def call(tool, **arguments):
            result=await client.call_tool(tool,arguments)
            assert not result.is_error,result
            return result.structured_content
        source={'material':'ArtistFinish','group_path':['Finish Controls','Inner Layer'],
                'node':'Pattern','socket':'Color','role':'data'}
        request={'map':'shader','name':'TileGrid','path':'channel.exr','source':source,
                 'uv_layer':'BakeUV','resolution':64,'samples':1,'margin':0}
        assert (await client.call_tool('bake',request)).is_error
        assert not (root/'channel.exr').exists()
        state=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='channel-author',
            expected_project=state['project_id']))['lease_id']
        await call('assign_material',action='set_image',material_name='ArtistFinish',
            group_path=source['group_path'],node='Pattern',lease_id=lease,
            image={'path':'glaze.<UDIM>.exr','tiles':[1001,1002,1011,1012],'color_space':'Non-Color'})
        before=await call('assign_material',action='inspect',material_name='ArtistFinish',
                          group_path=source['group_path'])
        result=await call('bake',**request,lease_id=lease)
        types=exr_channel_types(root/'channel.exr')
        assert types=={'B':2,'G':2,'R':2},types
        assert result['bit_depth']==32 and result['color_space']=='Non-Color'
        assert result['source']['minimum']<0 and result['source']['maximum']>1
        assert hashlib.sha256((root/'channel.exr').read_bytes()).hexdigest()==result['sha256']
        mask=await call('bake',map='shader',name='TileGrid',path='roughness.png',
            source={**source,'node':'Hero Surface','socket':'Roughness','direction':'INPUT'},
            uv_layer='BakeUV',resolution=64,samples=1,margin=0,lease_id=lease)
        assert mask['bit_depth']==16 and (root/'roughness.png').read_bytes()[24:26]==bytes([16,2])
        assert (await client.call_tool('bake',{**request,'lease_id':lease})).is_error
        assert hashlib.sha256((root/'channel.exr').read_bytes()).hexdigest()==result['sha256']
        after=await call('assign_material',action='inspect',material_name='ArtistFinish',
                         group_path=source['group_path'])
        assert before==after
        await call('session_control',action='release',lease_id=lease)
        assert len((await client.list_tools()).tools)==20
        return {'mcp_version':initialized.server_info.version,'tool_count':20,
            'exr_channel_types':types,'png_bits':mask['bit_depth'],
            'source_graph_unchanged':True,'lease_and_collision_checked':True,
            'signed_hdr_range':[result['source']['minimum'],result['source']['maximum']]}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('shader_bake_fixture.py'))

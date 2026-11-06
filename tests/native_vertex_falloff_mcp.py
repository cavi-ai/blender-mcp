"""One physical proportional-edit case through real MCP and native source data."""
from pathlib import Path

from native_nla_mcp import main
from native_vertex_edit_mcp import exercise


async def proportional(root,env,parameters=None):
    return await exercise(root,env,parameters=parameters,proportional=True)


if __name__ == '__main__':
    main(proportional,Path(__file__).with_name('vertex_falloff_fixture.py'))

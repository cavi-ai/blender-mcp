"""One symmetric proportional case through real MCP and native source data."""
from pathlib import Path

from native_nla_mcp import main
from native_vertex_edit_mcp import exercise


async def symmetric(root,env,parameters=None):
    return await exercise(root,env,parameters=parameters,symmetry=True)


if __name__ == '__main__':
    main(symmetric,Path(__file__).with_name('vertex_symmetry_fixture.py'))

# Version and support

## Versioning

The project uses Semantic Versioning. Before 1.0, the tool surface, action
parameters and result fields can still change. Every change is recorded in the
repository [CHANGELOG.md](https://github.com/cavi-ai/blender-mcp/blob/main/CHANGELOG.md).

Upgrade the server and the bridge together: run
`uv tool upgrade cavi-blender-mcp`, then close the dedicated Blender session and
run `cavi-blender-mcp runtime start` again. Running an older bridge against a
newer server can produce protocol refusals.

## Documentation versions

Documentation is built from the release commit and published under
`/docs/blender-mcp/v<version>`. The stable alias `/docs/blender-mcp` points to
the current release. Older release artifacts stay available on GitHub Releases.

## Support

Supported releases are the latest tagged release on `main`. Before 1.0, older
releases are not patched.

Report defects through GitHub issues. Report vulnerabilities privately as
described in [SECURITY.md](https://github.com/cavi-ai/blender-mcp/blob/main/SECURITY.md).

## Compatibility

- Blender 5.2.3 LTS is the tested release.
- Python 3.11 or newer is required for the MCP server.
- macOS and Linux are the tested platforms.
- Unity, Unreal and Godot exports are validated for bounds and naming, not for a
  specific engine version's import behavior.

## License

The project is MIT licensed. Third-party product names belong to their owners.
No vendor assets, logos or presets are included, and no endorsement is implied.

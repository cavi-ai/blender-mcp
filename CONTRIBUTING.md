# Contributing

## Setup

Install Python 3.11 or newer, `uv`, Node.js 22 or newer, and Blender 5.2.3 LTS
for native checks. Then:

```bash
uv sync --locked --dev
npm ci
uv run --locked python -m unittest discover -s tests
uv run --locked ruff check .
npm run eval:protocol
```

The unit suite does not need Blender. Native checks under `tests/blender_*.py`
run against a disposable factory scene and an empty workspace:

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python tests/blender_smoke.py -- /path/to/empty/workspace
```

## Where changes go

- MCP tool schemas and action routing: `src/cavi_blender_mcp/server.py`
- Transport, timeouts and connection validation: `src/cavi_blender_mcp/client.py`
- Shared operation and lease policy: `src/cavi_blender_mcp/operations.py`
- Blender-side dispatch and imports: `src/cavi_blender_mcp/blender_bridge.py`
- Feature modules: `src/cavi_blender_mcp/blender_*.py`
- Import preflight and path boundaries: `src/cavi_blender_mcp/importing.py`,
  `src/cavi_blender_mcp/paths.py`
- Documentation source: `docs/blender-mcp/source`
- MCP evaluation corpus: `evals/cases.json`

## Rules for changes

- Every change ships with a test that fails without it.
- Keep inputs bounded. Every new tool or action needs explicit name, count,
  size, pixel, triangle or time limits.
- When Blender's API does not expose an operation, report the boundary and fail
  closed. Do not simulate an unsupported write.
- Never retry an uncertain mutation. Return a diagnostic that says the outcome
  may be unknown.
- Do not add arbitrary code execution, network access, telemetry or external
  asset downloads.
- Mutations require a lease and must preserve scene state on failure.
- Update `reference/tools.md`, the README tool count and `evals/cases.json` when
  the tool surface changes.
- Keep a pull request to one concern.

## Commits

Use Conventional Commit prefixes: `feat:`, `fix:`, `docs:`, `chore:`, `test:`.

## Security

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

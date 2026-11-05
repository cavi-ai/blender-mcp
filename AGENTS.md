# blender-mcp: hard rules

These rules bind every agent and every change in this repository.

## Hard rules

### Versions come from git tags

- Feature and fix PRs never change a version: not `pyproject.toml`, `uv.lock` or a CHANGELOG heading.
- Add CHANGELOG lines under `## Unreleased`.
- An official release happens only when the owner calls it: bump `pyproject.toml` to that version in a
  release PR, merge it, and push the tag `vX.Y.Z`. The tag publishes the release.
- No workflow bumps a version, tags or releases on push to main.

### Test the thing you changed

- Run the unit module(s) your change touches and `ruff check`. Do not run the full suite for a scoped change.
- CI and local gates never launch Blender. Native checks under `tests/blender_*.py` are optional and
  scoped to one script for the behavior you changed.
- Never start a long native run to check a change.

### Keep output tidy

- Working files go in a task's own scratch folder, never loose in the repository or its parent.
- Clean the scratch folder when the task ends.

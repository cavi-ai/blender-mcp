# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- `level_edit` for heightmap or procedural terrain, bulk object placement and
  surface snapping with bounded terrain and assembly budgets.
- USD texture sidecars through `asset_io` `textures=true`, with copied images,
  relative texture paths and a receipt.
- USD export of armature and shape-key animation through `asset_io`
  `animations=true`.
- Versioned documentation source, build, verification and release artifact
  tooling for cavi-ai.xyz.
- Release workflow that publishes the docs artifact and dispatches it to
  `cavi-ai/cavi-home`.
- PyPI publishing for `cavi-blender-mcp` on release tags; install it with
  `uv tool install cavi-blender-mcp` and start Blender with
  `cavi-blender-mcp runtime start`.
- License, security policy, contribution guide, code of conduct, issue forms,
  pull request template, Dependabot configuration and `CHANGELOG.md`.
- Unit tests for docs builds, navigation coverage, README links and artifact
  determinism.

### Changed

- README is restructured for first-time readers and links to the versioned
  documentation instead of duplicating it.
- Shared operation, lease and timeout policy moved to
  `src/cavi_blender_mcp/operations.py`.
- Bridge import rollback is one shared path for GLB, FBX, OBJ and USD imports.
- Package metadata now declares the license, project URLs and classifiers.

### Fixed

- Bridge client rejects malformed responses and HTTP protocol failures with a
  stable diagnostic instead of leaking parser exceptions.
- GLB preflight bounds nested JSON and validates embedded image buffer views.
- Empty connection and workspace environment variables fall back to defaults.
- The package requires `mcp` below 2.0, so an install from PyPI no longer
  resolves an `mcp` release without the server API it uses.

## 0.20.0 — 2026-10-31

### Added

- Animation retargeting through `rig_edit` action `retarget`, with matching-name
  or explicit bone mappings, whole-frame or sampled baking, and mapped and
  unmapped bone reports.

## 0.19.0 — 2026-10-31

### Added

- Animation QA in `inspect_rig`: `root_motion`, `loop` and `deformation` checks
  over a named or active action, with bounded sampling and scene restoration.

## 0.18.0 — 2026-10-31

Initial public tool surface. Earlier `0.1.0` through `0.17.0` builds were
pre-public development snapshots; their changes are included here.

### Added

- 13 typed MCP tools for scene inspection, mesh quality and rig inspection,
  object and mesh editing, PBR materials, baking, asset import and export,
  previews, review sheets, scatter and session ownership.
- Bounded GLB, FBX, OBJ and USD import with preflight validation, workspace
  confinement and rollback on failure.
- Static, skinned and animated FBX/GLB export with Unity, Unreal and Godot axis
  presets, LOD groups, collision naming and bake-pair naming.
- Normal and ambient-occlusion baking, Smart UV Project helpers, lightmap
  overlap measurement and texel-density correction.
- Armature creation, automatic skin binding, weight repair, pose authoring and
  action creation.
- Optional offline image-to-3D generation through local TripoSR weights.
- Runtime CLI for starting, inspecting and restarting a dedicated Blender
  bridge session, including headless mode.
- MCP evaluation corpus and protocol checks pinned to `@cavi-ai/mcp-eval` 0.8.0.

### Security

- Loopback-only bridge with a private bearer token and connection file.
- Workspace-confined paths with symlink resolution and no overwrite.
- Lease-bound mutations with project identity checks and no automatic retries.

## Pre-public development builds

| Version | Change |
| --- | --- |
| 0.17.0 | OBJ import |
| 0.16.0 | Normal and AO baking |
| 0.15.0 | Animated FBX import |
| 0.14.0 | FBX import |
| 0.13.0 | Animated GLB import |
| 0.12.0 | Rigged GLB import |
| 0.11.0 | Pose authoring and animated export |
| 0.10.0 | Armature creation and skin binding |
| 0.9.0 | PBR materials and material QA |
| 0.8.0 | Composition and assembly tooling |
| 0.7.1 | Golden-asset fixes for hulls, lightmaps, LODs and review sheets |
| 0.7.0 | Character rig and skin-weight inspection |
| 0.6.0 | AAA geometry tooling |
| 0.5.0 | Consolidated tools and hardened bridge |
| 0.4.0 | Mesh quality inspection and FBX instance preservation |
| 0.3.0 | Textured materials and lit previews |
| 0.2.0 | Blender edit ownership |
| 0.1.0 | Scene and export tools |

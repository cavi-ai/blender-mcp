# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## 0.42.0 - 2026-11-04

- Add rest-relative retarget calibration with explicit root travel scaling.
- Measure declared bone contact windows for drift and ground-height error.
- Allow explicit linear skinning on independent bake copies while preserving authored modifiers.
- Preserve clip inspection poses, NLA state and subframes.

## 0.41.0 - 2026-11-04

- Preserve verified preflight rejection outcomes for transfer, bake and retarget operations.
- Keep post-edit, transport and unmarked native failures unknown and non-retryable.

## 0.40.0 - 2026-11-04

- Inspect sampled garment clearance against closed evaluated body components.
- Report signed gaps, failing probes, topology and bounded query completeness.
- Share evaluated mesh sampling between motion and clearance inspections.

## 0.39.0 - 2026-11-04

- Transfer selected relative morphs alongside skin weights using the same surface projection.
- Preserve mask and relative-key deltas across transforms and follow donor weight/mute channels.

## 0.38.0 - 2026-11-03

- Transfer rest-surface skin weights onto independent clothing or retopology copies.
- Reject distance and discarded-influence budget failures before editing.

## 0.37.0 - 2026-11-03

- Compare evaluated skinned motion and bone heads in metres without changing the timeline.
- Bake fractional frames and driven shape weights onto independent export copies.
- Preserve subframe GLB keys and export a sampled active FBX take with import identity metadata.
- Accept bounded FBX shape-key imports.

## Unreleased

### Added

- TripoSG image-to-3D provider on Apple Silicon, CUDA or CPU, selected with `CAVI_GENERATION_PROVIDER`.

## 0.36.0 - 2026-11-03

### Added

- Material-filtered UV inspection with source face counts and used slot bindings.

## 0.35.0 - 2026-11-03

### Added

- Saved source hashes captured at Blender load/save boundaries, with current dirty state.

## 0.34.0 - 2026-11-03

### Added

- Loaded bridge protocol and source fingerprints with runtime compatibility checks.
- Pinned shared response-schema helpers and a source synchronization check.

### Fixed

- Propagate Python bridge startup failures through Blender's exit status.

## 0.33.0 - 2026-11-03

### Added

- Typed IK, pole and rotation-limit authoring, exact vertex weights and independent evaluated FK animation bakes.
- Persistent cameras, lights, packed HDRI worlds and production Cycles/Eevee rendering with 16-bit defaults.

### Fixed

- Export baked rig and mesh transforms as one glTF animation, excluding unrelated actions.
- Preserve high precision texture sidecars and apply color encoding once; reject implicit HDR clipping.
- Snapshot exact HDRI bytes independently of stale cached image buffers.


### Added

- Read-only UV layout preflight with analytic overlap, chart and tile-border padding measurements.
- Explicit incomplete results when the bounded UV comparison budget is exhausted.

### Fixed

- Isolate copied bake materials and route every face to the private output image, preserving original texture buffers and material overrides.

- Preserve floating-point bake samples through 16-bit PNG output by default, with explicit precision metadata.
- Encode raw data maps and sRGB lightmaps independently of scene view settings.
- Use canonical normal channels and restore the scene's original swizzles after baking.
- Refuse incompatible bake bridges before writing output.

- Accept mesh separation results and named-object collection lists in MCP responses.
- Preserve supplied transparency in reconstruction references, including white foreground details.
- Convert reconstructed vertex colors from sRGB to linear RGB for glTF export, preserving alpha.

## 0.32.0 — 2026-11-02

### Added

- Declared response fields for rig inspection, native edits, materials, bakes, levels and scatter.
- Action-specific response validation that preserves existing wire shapes and extra details.
- Report output conversion failures as uncertain outcomes without suggesting a retry.

## 0.31.0 — 2026-11-02

### Added

- Declared response fields for scene inspection, mesh quality, edit ownership and asset transfer.
- Structured error codes, outcome and recovery hints alongside readable MCP errors.

### Changed

- Omit redundant schema titles from discovery while retaining validation constraints.

## 0.30.0 — 2026-10-31

### Changed

- Requires the MCP Python SDK 2.3 or later, so it installs alongside
  `cavi-substance-mcp`. Invalid arguments, refused paths and bridge failures
  are still reported to the client; other exceptions are reported without
  their details. `serverInfo.version` reports the package version.

## 0.29.0 — 2026-10-31

### Added

- `level_edit` for heightmap or procedural terrain, bulk object placement and
  surface snapping with bounded terrain and assembly budgets.
- FBX and USD texture sidecars through `asset_io` `textures=true`, with copied
  images, relative texture paths and a receipt.
- USD export of armature and shape-key animation through `asset_io`
  `animations=true`.
- Action and NLA clip management: `inspect_rig` lists actions, `rig_edit` sets,
  renames and deletes actions, and NLA push and remove build clip libraries for
  multi-action export.
- Shape-key authoring: add, set and remove shape keys from sparse offsets or a
  source mesh, and key them atomically from frame and value lists.
- GLB morph targets: bounded shape-key import, shape-key export on static and
  animated GLBs, shape-key animation import and export, and morph-only animated
  GLBs; object inspection reports shape keys and the active shape-key action.
- Curvature baking from Cycles pointiness and diffuse lightmap baking that keeps
  the scene's lights.
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
- `assign_material` binds materials to mesh data, so FBX exports include them.

### Fixed

- Texture sidecar exports write copies of the scene's images, so generated
  images and unsaved paint keep their pixels after an export.
- Noise terrain caps each octave's lattice at the mesh resolution, which keeps
  the densest request near the mesh's own memory; high-frequency octaves above
  the resolution produce different heights than before.
- A placement that fails part-way removes every copy it made and the collection
  it created or linked.
- `requirements-neural.txt` installs again: `opencv-python-headless`, `mpmath`
  and `rembg` are pinned to releases compatible with `numpy` 1.26.4 and
  `sympy`, and CI resolves the file on every change.
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

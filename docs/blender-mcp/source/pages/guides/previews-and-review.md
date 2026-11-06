# Preview and review

Both preview tools are read-only, return an MCP image and need no lease. They
restore scene state afterward.

## Single preview

`render_preview` writes a PNG to a new workspace path and returns it as an MCP
image.

| Parameter | Meaning |
| --- | --- |
| `path` | New workspace `.png` path |
| `resolution` | Square size 64–2048, default 512 |
| `names` | Optional meshes to isolate; other renderables are hidden |
| `direction` | Camera direction from the scene center |
| `color_mode` | `material` or `vertex` |
| `renderer` | `workbench` or `eevee` |
| `orthographic` | Use an orthographic camera |
| `settings` | Optional temporary display controls and PNG precision |

Workbench checks shape. Eevee checks materials under temporary studio lighting
at up to 1024 pixels and requires material colors.

Pass `settings` for a reproducible display profile. Its defaults are sRGB display,
AgX, look `None`, exposure 0, gamma 1 and 16-bit RGBA PNG. Override `display_device`,
`view_transform`, `look`, `exposure`, `gamma` or `bit_depth` explicitly as needed.
The selected display, transform and look must exist in the loaded OCIO configuration.
Exposure and gamma must also fit the native Blender property ranges.

`use_curve_mapping`, `use_white_balance` and `use_compositing` default to false.
Enabling a toggle reuses the scene's existing curves, balance or compositor; the
preview does not edit their contents. White balance requires a supporting Blender
runtime. Omit `settings` to retain the scene's display controls and PNG settings.
All overridden controls and the original output format, color mode and precision
are restored after rendering, including failures. Previews need no edit lease.

`scene_info` reports the current `render_settings`, including display controls,
compositing, image format and precision. These describe the source scene; temporary
preview settings apply only while the image is rendered.

## Review sheet

`review_sheet` renders up to six views into one contact sheet exactly
`resolution` pixels wide.

Views: `front`, `back`, `left`, `right`, `top` and `persp`.

Modes:

| Mode | Purpose |
| --- | --- |
| `shaded` | Studio shading |
| `wireframe` | Temporary wireframe stand-ins |
| `uv_checker` | UV layout with a generated checker texture |
| `texel_heatmap` | Blue below, green on and red above a target density |
| `matcap` | Material capture lighting |

`target_px_per_m` and `texture_resolution` apply only to `texel_heatmap`.
`uv_layer` applies to `texel_heatmap` and `uv_checker`.

Source meshes are bounded to 500,000 triangles. Copy-based modes are bounded to
200,000 triangles.

## Related

- [Materials and UVs](materials-and-uvs.md)
- [Inspect a scene](scene-inspection.md)

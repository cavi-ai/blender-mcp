"""CPU TripoSR adapter using local weights and scikit-image mesh extraction."""

import contextlib
import hashlib
import json
import os
import sys
import types
from pathlib import Path


def clean_mesh(mesh):
    from trimesh.smoothing import filter_taubin

    components = mesh.split(only_watertight=False)
    if not len(components):
        raise ValueError("Reconstruction has no connected surface")
    mesh = max(components, key=lambda component: len(component.faces))
    filter_taubin(mesh, lamb=0.5, nu=0.53, iterations=4)
    mesh.fix_normals()
    return mesh


BACKDROP_TOLERANCE = 48
BACKDROP_BORDER_SHARE = 0.9
BACKDROP_WORK_SIDE = 1024


def backdrop_alpha(rgb):
    """Alpha for an opaque image: 0 on the plain backdrop reached from the border, 255 elsewhere.

    Pixels the subject encloses keep their colour, so white eyes and clothes survive a white backdrop.
    """
    from collections import deque

    import numpy as np
    from PIL import Image

    small = rgb.convert("RGB")
    small.thumbnail((BACKDROP_WORK_SIDE, BACKDROP_WORK_SIDE), Image.Resampling.BILINEAR)
    width, height = small.size
    colours = np.asarray(small, dtype=np.int16)
    edge = np.zeros((height, width), dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    backdrop = np.median(colours[edge], axis=0)
    close = np.abs(colours - backdrop).max(axis=2) <= BACKDROP_TOLERANCE
    if close[edge].mean() < BACKDROP_BORDER_SHARE:
        raise ValueError(
            "Input image has no transparency and no plain background; supply a cutout with alpha"
        )
    reached = edge & close
    queue = deque(zip(*np.nonzero(reached)))
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < height and 0 <= nx < width and close[ny, nx] and not reached[ny, nx]:
                reached[ny, nx] = True
                queue.append((ny, nx))
    mask = Image.fromarray(np.where(reached, 0, 255).astype(np.uint8))
    return mask.resize(rgb.size, Image.Resampling.BILINEAR)


def prepare_image(source, background=(128, 128, 128), extent=435):
    """Frame the subject inside a 512-pixel square on a flat background."""
    from PIL import Image

    with Image.open(source) as original:
        if original.width > 4096 or original.height > 4096:
            raise ValueError("Input image must be at most 4096 pixels per side")
        rgba = original.convert("RGBA")
        # An existing cutout is authoritative; an opaque image loses only its plain backdrop.
        if rgba.getchannel("A").getextrema()[0] == 255:
            rgba.putalpha(backdrop_alpha(rgba))
        cutout = rgba
        bounds = cutout.getbbox()
        if bounds is None:
            raise ValueError("Input image has no visible foreground")
        cutout = cutout.crop(bounds)
        cutout.thumbnail((extent, extent), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (512, 512), (*background, 255))
        canvas.alpha_composite(cutout, ((512 - cutout.width) // 2, (512 - cutout.height) // 2))
        return canvas.convert("RGB")


def linearize_vertex_colors(colors):
    """Convert TripoSR's display RGB to glTF's linear COLOR_0; preserve alpha."""
    import numpy as np

    result = colors.copy()
    rgb = colors[:, :3].astype(np.float32) / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    result[:, :3] = np.rint(linear * 255).astype(np.uint8)
    return result


def main():
    # Heavy libraries stay in a separate configured environment, outside Blender and MCP.
    import numpy as np
    import torch
    from omegaconf import OmegaConf
    from skimage.measure import marching_cubes

    torch.set_num_threads(4)
    torch.manual_seed(0)
    source, output, resolution = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    weights = Path(os.environ["CAVI_TRIPOSR_WEIGHTS"])
    sys.path.insert(0, os.environ["CAVI_TRIPOSR_SOURCE"])
    # The upstream CUDA extension is unnecessary for CPU isosurface extraction.
    adapter = types.ModuleType("torchmcubes")

    def extract(level, threshold):
        vertices, faces, _, _ = marching_cubes(level.cpu().numpy(), threshold)
        return (
            torch.from_numpy(vertices[:, [2, 1, 0]].copy()),
            torch.from_numpy(faces.astype(np.int64).copy()),
        )

    adapter.marching_cubes = extract
    sys.modules["torchmcubes"] = adapter
    with contextlib.redirect_stdout(sys.stderr):
        from tsr.models.tokenizers import image as image_tokenizer
        from tsr.system import TSR

        def local_config(repo_id, filename):
            if repo_id != "facebook/dino-vitb16" or filename != "config.json":
                raise ValueError("Unexpected tokenizer configuration")
            return str(weights / "dino-config.json")

        image_tokenizer.hf_hub_download = local_config
        config = OmegaConf.load(weights / "config.yaml")
        OmegaConf.resolve(config)
        model = TSR(config).eval()
        state = torch.load(weights / "model.ckpt", map_location="cpu", weights_only=True, mmap=True)
        model.load_state_dict(state)
        del state
        model.renderer.set_chunk_size(16384)
        prepared = prepare_image(source)
        with torch.inference_mode():
            codes = model([prepared], device="cpu")
            mesh = model.extract_mesh(codes, has_vertex_color=True, resolution=resolution)[0]
        if not 0 < len(mesh.faces) <= 500000:
            raise ValueError("Reconstructed mesh exceeded 500000 faces or was empty")
        mesh = clean_mesh(mesh)
        mesh.visual.vertex_colors = linearize_vertex_colors(mesh.visual.vertex_colors)
        # TripoSR uses Z-up with its conditioning view along +X. glTF uses Y-up.
        mesh.vertices = mesh.vertices[:, [1, 2, 0]]
        mesh.export(str(output))
    print(
        json.dumps(
            {
                "provider": "TripoSR",
                "device": "cpu",
                "resolution": resolution,
                "vertices": len(mesh.vertices),
                "triangles": len(mesh.faces),
                "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()

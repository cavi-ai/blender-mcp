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


def main():
    # Heavy libraries stay in a separate configured environment, outside Blender and MCP.
    import numpy as np
    import torch
    from omegaconf import OmegaConf
    from PIL import Image
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
        with Image.open(source) as original:
            if original.width > 4096 or original.height > 4096:
                raise ValueError("Input image must be at most 4096 pixels per side")
            rgba = np.array(original.convert("RGBA"))
            # Match upstream's gray-background conditioning and 85% foreground framing.
            alpha = rgba[:, :, 3].astype(np.float32) / 255
            alpha *= np.clip((255 - rgba[:, :, :3].min(axis=2).astype(np.float32)) / 12, 0, 1)
            rgba[:, :, 3] = (alpha * 255).astype(np.uint8)
            cutout = Image.fromarray(rgba)
            bounds = cutout.getbbox()
            if bounds is None:
                raise ValueError("Input image has no visible foreground")
            cutout = cutout.crop(bounds)
            cutout.thumbnail((435, 435), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (512, 512), (128, 128, 128, 255))
            canvas.alpha_composite(cutout, ((512 - cutout.width) // 2, (512 - cutout.height) // 2))
            prepared = canvas.convert("RGB")
        with torch.inference_mode():
            codes = model([prepared], device="cpu")
            mesh = model.extract_mesh(codes, has_vertex_color=True, resolution=resolution)[0]
        if not 0 < len(mesh.faces) <= 500000:
            raise ValueError("Reconstructed mesh exceeded 500000 faces or was empty")
        mesh = clean_mesh(mesh)
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

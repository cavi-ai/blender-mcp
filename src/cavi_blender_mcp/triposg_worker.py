"""TripoSG adapter using local weights on Apple Silicon, CUDA or CPU with scikit-image extraction."""

import contextlib
import hashlib
import json
import os
import sys
import types
from pathlib import Path

from neural_worker import prepare_image

MAX_TRIANGLES = 500000


def bounded(vertices, faces):
    import pymeshlab
    import trimesh

    if len(faces) > MAX_TRIANGLES:
        meshes = pymeshlab.MeshSet()
        meshes.add_mesh(pymeshlab.Mesh(vertices, faces))
        meshes.meshing_decimation_quadric_edge_collapse(
            targetfacenum=MAX_TRIANGLES, preservenormal=True, preservetopology=True, qualitythr=0.5
        )
        reduced = meshes.current_mesh()
        vertices, faces = reduced.vertex_matrix(), reduced.face_matrix()
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    if not 0 < len(mesh.faces) <= MAX_TRIANGLES:
        raise ValueError(f"Reconstruction must have between 1 and {MAX_TRIANGLES} faces")
    mesh.fix_normals()
    return mesh


def main():
    # Unsupported Metal kernels run on the CPU instead of aborting the worker.
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    import numpy as np
    import torch

    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, os.environ["CAVI_TRIPOSG_SOURCE"])
    # The flash decoder needs a CUDA-only extension; the hierarchical decoder uses scikit-image.
    sys.modules["diso"] = types.SimpleNamespace(DiffDMC=None)
    if torch.backends.mps.is_available():
        device, dtype = "mps", torch.float16
    elif torch.cuda.is_available():
        device, dtype = "cuda", torch.float16
    else:
        device, dtype = "cpu", torch.float32
    with contextlib.redirect_stdout(sys.stderr):
        from triposg import inference_utils
        from triposg.pipelines.pipeline_triposg import TripoSGPipeline

        upstream_expand = inference_utils.expand_edge_region_fast

        def expand_on_device(edge_coords, grid_size):
            # Upstream allocates this band grid on CUDA; allocate it beside the coordinates.
            zeros = torch.zeros

            def local_zeros(*size, device=None, **kwargs):
                return zeros(*size, device=edge_coords.device, **kwargs)

            torch.zeros = local_zeros
            try:
                return upstream_expand(edge_coords, grid_size)
            finally:
                torch.zeros = zeros

        inference_utils.expand_edge_region_fast = expand_on_device
        pipeline = TripoSGPipeline.from_pretrained(os.environ["CAVI_TRIPOSG_WEIGHTS"])
        pipeline = pipeline.to(device, dtype)
        prepared = prepare_image(source, background=(255, 255, 255), extent=427)
        with torch.inference_mode():
            vertices, faces = pipeline(
                image=prepared,
                generator=torch.Generator(device="cpu").manual_seed(0),
                num_inference_steps=50,
                guidance_scale=7.0,
                use_flash_decoder=False,
            ).samples[0]
        if vertices is None:
            raise ValueError("Reconstruction has no surface")
        mesh = bounded(np.asarray(vertices, dtype=np.float32), np.ascontiguousarray(faces))
        mesh.export(str(output))
    print(
        json.dumps(
            {
                "provider": "TripoSG",
                "device": device,
                "vertices": len(mesh.vertices),
                "triangles": len(mesh.faces),
                "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()

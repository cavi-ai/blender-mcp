"""TripoSG adapter using local weights on Apple Silicon, CUDA or CPU with scikit-image extraction."""

import contextlib
import hashlib
import json
import os
import sys
import types
from pathlib import Path

from triposg_frame import frame


def bounded(vertices, faces, max_faces):
    import pymeshlab
    import trimesh

    if len(faces) > max_faces:
        meshes = pymeshlab.MeshSet()
        meshes.add_mesh(pymeshlab.Mesh(vertices, faces))
        meshes.meshing_decimation_quadric_edge_collapse(
            targetfacenum=max_faces, preservenormal=True, preservetopology=True, qualitythr=0.5
        )
        reduced = meshes.current_mesh()
        vertices, faces = reduced.vertex_matrix(), reduced.face_matrix()
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    if not 0 < len(mesh.faces) <= max_faces:
        raise ValueError(f"Reconstruction must have between 1 and {max_faces} faces")
    mesh.fix_normals()
    return mesh


def main():
    # Unsupported Metal kernels run on the CPU instead of aborting the worker.
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    import numpy as np
    import torch

    # Options: steps, guidance, seed and max_faces, resolved by the server from its configuration.
    source, output, options = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3])
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
        prepared = frame(source)
        with torch.inference_mode():
            vertices, faces = pipeline(
                image=prepared,
                generator=torch.Generator(device="cpu").manual_seed(options["seed"]),
                num_inference_steps=options["steps"],
                guidance_scale=options["guidance"],
                use_flash_decoder=False,
            ).samples[0]
        if vertices is None:
            raise ValueError("Reconstruction has no surface")
        mesh = bounded(np.asarray(vertices, dtype=np.float32), np.ascontiguousarray(faces), options["max_faces"])
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

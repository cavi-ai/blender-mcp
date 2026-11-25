"""Optional offline image-to-mesh worker; no downloads or account access."""

import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path

from cavi_mcp_core import proc
from cavi_mcp_core import workspace as core_workspace

from .importing import MAX_BYTES, MAX_GEOMETRY
from .paths import destination

MLX_MAX_FACES = 500000
PROVIDERS = {
    "triposr": {
        "prefix": "CAVI_TRIPOSR",
        "suffixes": ("PYTHON", "SOURCE", "WEIGHTS"),
        "worker": "neural_worker.py",
        "timeout": 180,
    },
    "triposg": {
        "prefix": "CAVI_TRIPOSG",
        "suffixes": ("PYTHON", "SOURCE", "WEIGHTS"),
        "worker": "triposg_worker.py",
        "timeout": 600,
    },
    "triposg-mlx": {
        "prefix": "CAVI_TRIPOSG_MLX",
        "suffixes": ("PYTHON", "AGENT", "MODEL"),
        "timeout": 600,
        "model": "TripoSG",
        "frame": "triposg_frame.py",
        "quality": {
            "default": ("--steps", "50", "--resolution", "512"),
            "fast": ("--steps", "25", "--resolution", "256", "--denoiser-cache", "adaptive"),
        },
    },
    "trellis2-mlx": {
        "prefix": "CAVI_TRELLIS2_MLX",
        "suffixes": ("PYTHON", "AGENT", "MODEL"),
        "timeout": 600,
        "model": "TRELLIS.2",
        "frame": "trellis2_frame.py",
        # Default keeps the converted checkpoint's sampler steps and guidance.
        "quality": {
            "default": ("--resolution", "512"),
            "fast": ("--steps", "6", "--resolution", "512"),
        },
        "vertex_colors": True,
        "guides": True,
        # Atlas export duplicates each triangle corner; also bound the embedded GLB.
        "fast_max_faces": min(180_000, MAX_GEOMETRY // 3),
    },
}
QUALITIES = ("fast", "default")
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_VIEWS = 5
# mlx-agent keeps the smallest bbox side at least two voxels of TRELLIS.2's 32³ sparse structure.
MAX_BOX_RATIO = 16


def envelope_error(result):
    """Describe a failed mlx-agent result envelope, if its output is one."""
    try:
        error = json.loads(result.stdout)["error"]
        return f"{error['code']}: {error['message']}"
    except (ValueError, KeyError, TypeError):
        return None


def run(command, env, timeout, deadline, describe=None):
    left = deadline - time.monotonic()
    try:
        if left <= 0:
            raise TimeoutError
        result = proc.run_sync(command, left, env=env)
    except TimeoutError as exc:
        raise RuntimeError(
            f"Local reconstruction exceeded {timeout} seconds; no asset published"
        ) from exc
    if result.returncode:
        detail = (describe and describe(result)) or proc.diagnostics(result)
        raise RuntimeError(
            f"Local reconstruction failed (exit {result.returncode}): {detail[-2000:]}"
        )
    return result


def mlx_mesh(settings, configured, source, generated, env, timeout, deadline, quality, views=(), guide=None,
             bbox=None):
    """Frame the images for the model, then run the mlx-agent mesh command."""
    framed = generated.with_name("framed.png")
    frame = Path(__file__).with_name(settings["frame"])
    run([configured["PYTHON"], str(frame), str(source), str(framed)], env, timeout, deadline)
    extra = []
    for index, view in enumerate(views):
        framed_view = generated.with_name(f"view-{index}.png")
        run([configured["PYTHON"], str(frame), str(view), str(framed_view)], env, timeout, deadline)
        extra += ["--view", str(framed_view)]
    if guide is not None:
        extra += ["--guide", str(guide)]
    if bbox is not None:
        extra += ["--bbox", *(str(size) for size in bbox)]
    # The agent stops itself first, so a timeout is reported by its envelope.
    agent_timeout = max(1, int(deadline - time.monotonic()) - 30)
    max_faces = settings.get("fast_max_faces", MLX_MAX_FACES) if quality == "fast" else MLX_MAX_FACES
    command = [
        configured["PYTHON"],
        configured["AGENT"],
        "convert",
        "mesh",
        "--path",
        configured["MODEL"],
        "--image",
        str(framed),
        "--out",
        str(generated),
        *settings["quality"][quality],
        *extra,
        "--seed",
        "42",
        "--max-faces",
        str(max_faces),
        "--timeout",
        str(agent_timeout),
        "--json",
    ]
    result = run(command, env, timeout, deadline, envelope_error)
    try:
        envelope = json.loads(result.stdout)
        if envelope["status"] != "ok":
            raise ValueError(envelope["status"])
        data = envelope["data"]
        report = {
            "provider": settings["model"],
            "backend": data["backend"],
            "vertices": data["vertices"],
            "faces": data["faces"],
            "seconds": data["seconds"],
            "stage_seconds": data["stage_seconds"],
            "peak_memory_gb": data["peak_memory_gb"],
            "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "quality": quality,
        }
        if settings.get("vertex_colors"):
            # A checkpoint converted without the texture stage writes the mesh uncolored.
            report["vertex_colors"] = data["vertex_colors"]
            if type(report["vertex_colors"]) is not bool:
                raise TypeError("vertex_colors")
        if views or guide is not None:
            report.update(views=data["views"], guided=data["guided"],
                          view_sha256=[hashlib.sha256(view.read_bytes()).hexdigest() for view in views])
            if report["views"] != 1 + len(views) or report["guided"] is not (guide is not None):
                raise ValueError("views")
            if guide is not None:
                report["guide_sha256"] = hashlib.sha256(guide.read_bytes()).hexdigest()
        if bbox is not None:
            report["bbox"] = data["bbox"]
            if report["bbox"] != bbox:
                raise ValueError("bbox")
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("mlx-agent returned no usable mesh result") from exc
    if type(report["faces"]) is not int or not 0 < report["faces"] <= max_faces:
        raise RuntimeError(f"Reconstruction must have between 1 and {max_faces} faces")
    return report


def inside(workspace, relative, suffixes, limit, message):
    """An existing workspace file with an accepted suffix and size, else ``ValueError(message)``."""
    try:
        resolved = core_workspace.input_file(workspace, relative, suffixes)
    except ValueError:
        raise ValueError(message) from None
    if not 0 < resolved.stat().st_size <= limit:
        raise ValueError(message)
    return resolved


def generate(workspace, image, path, resolution=None, quality=None, views=None, guide=None, bbox=None):
    provider = os.environ.get("CAVI_GENERATION_PROVIDER", "triposr")
    if provider not in PROVIDERS:
        raise ValueError(
            "CAVI_GENERATION_PROVIDER must be triposr, triposg, triposg-mlx or trellis2-mlx"
        )
    settings = PROVIDERS[provider]
    quality = "default" if quality is None else quality
    if quality not in QUALITIES:
        raise ValueError("Quality must be fast or default")
    if quality != "default" and "quality" not in settings:
        raise ValueError("Quality tiers apply only to the triposg-mlx and trellis2-mlx providers")
    workspace = Path(workspace).resolve()
    source = inside(workspace, image, IMAGES, 16 * 1024 * 1024,
                    "Input image must be a workspace PNG, JPEG or WebP image of at most 16 MiB")
    views = list(views or ())
    if (views or guide is not None or bbox is not None) and not settings.get("guides"):
        raise ValueError("Views, guides and bbox apply only to the trellis2-mlx provider")
    if bbox is not None:
        if (guide is not None or not isinstance(bbox, (list, tuple)) or len(bbox) != 3
                or any(type(size) not in (int, float) or not math.isfinite(size) or size <= 0 for size in bbox)
                or max(bbox) > MAX_BOX_RATIO * min(bbox)):
            raise ValueError(f"bbox takes three sizes above 0, at most {MAX_BOX_RATIO} times apart, and no guide")
        bbox = [float(size) for size in bbox]
    if len(views) > MAX_VIEWS:
        raise ValueError(f"Provide at most {MAX_VIEWS} views")
    views = [inside(workspace, view, IMAGES, 16 * 1024 * 1024,
                    "Each view must be a workspace PNG, JPEG or WebP image of at most 16 MiB") for view in views]
    if guide is not None:
        guide = inside(workspace, guide, {".glb"}, 64 * 1024 * 1024,
                       "The guide must be a workspace GLB of at most 64 MiB")
    target = destination(workspace, path, {".glb"})
    if provider == "triposr":
        resolution = 128 if resolution is None else resolution
        if type(resolution) is not int or not 64 <= resolution <= 192:
            raise ValueError("Resolution must be between 64 and 192")
        arguments = [str(resolution)]
    else:
        if resolution is not None:
            raise ValueError("Resolution applies only to the TripoSR provider")
        arguments = []
    configured = {}
    for suffix in settings["suffixes"]:
        key = f"{settings['prefix']}_{suffix}"
        value = os.environ.get(key)
        if not value or not Path(value).is_absolute() or not Path(value).exists():
            raise RuntimeError(f"Configure {key} with an existing absolute local path")
        configured[suffix] = value
    env = dict(
        os.environ,
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        OMP_NUM_THREADS="4",
    )
    timeout = settings["timeout"]
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix=".cavi-generation-", dir=workspace) as temporary:
        generated = Path(temporary) / "mesh.glb"
        if "frame" in settings:
            report = mlx_mesh(settings, configured, source, generated, env, timeout, deadline, quality,
                              views, guide, bbox)
        else:
            command = [
                configured["PYTHON"],
                str(Path(__file__).with_name(settings["worker"])),
                str(source),
                str(generated),
                *arguments,
            ]
            report = json.loads(run(command, env, timeout, deadline).stdout)
        if not generated.is_file():
            raise RuntimeError("Reconstruction did not produce a GLB")
        size = generated.stat().st_size
        if not size:
            raise RuntimeError("Reconstruction did not produce a GLB")
        if size > MAX_BYTES:
            raise RuntimeError(f"Reconstruction GLB is {size} bytes; maximum is {MAX_BYTES} bytes")
        # Publish without replacing an existing destination, even if another writer won the race.
        os.link(generated, target)
    return {**report, "path": str(target), "bytes": target.stat().st_size}

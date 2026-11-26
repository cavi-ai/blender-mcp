"""Optional offline image-to-mesh worker; no downloads or account access."""

import hashlib
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

from cavi_mcp_core import proc
from cavi_mcp_core import workspace as core_workspace

from .importing import MAX_BYTES, MAX_GEOMETRY, inspect_glb
from .paths import destination

# Atlas export duplicates each triangle corner.
ATLAS_MAX_FACES = min(180_000, MAX_GEOMETRY // 3)
# Built-in defaults. Each named value is read from CAVI_<PROVIDER>_<QUALITY>_<NAME>, then CAVI_<PROVIDER>_<NAME>;
# a mapping holds one default per quality tier.
PROVIDERS = {
    "triposr": {
        "prefix": "CAVI_TRIPOSR",
        "suffixes": ("PYTHON", "SOURCE", "WEIGHTS"),
        "worker": "neural_worker.py",
        "timeout": 180,
        "threads": 4,
        "worker_options": {"resolution": 128, "seed": 0, "max_faces": MAX_GEOMETRY, "chunk_size": 16384},
    },
    "triposg": {
        "prefix": "CAVI_TRIPOSG",
        "suffixes": ("PYTHON", "SOURCE", "WEIGHTS"),
        "worker": "triposg_worker.py",
        "timeout": 600,
        "threads": 4,
        "worker_options": {"steps": 50, "guidance": 7.0, "seed": 0, "max_faces": MAX_GEOMETRY},
    },
    "triposg-mlx": {
        "prefix": "CAVI_TRIPOSG_MLX",
        "suffixes": ("PYTHON", "AGENT", "MODEL"),
        "timeout": 600,
        "threads": 4,
        "model": "TripoSG",
        "frame": "triposg_frame.py",
        "seed": 42,
        "max_faces": MAX_GEOMETRY,
        # mlx-agent options of each quality tier.
        "quality": {
            "default": {"steps": 50, "resolution": 512, "denoiser-cache": "off"},
            "fast": {"steps": 25, "resolution": 256, "denoiser-cache": "adaptive"},
        },
    },
    "trellis2-mlx": {
        "prefix": "CAVI_TRELLIS2_MLX",
        "suffixes": ("PYTHON", "AGENT", "MODEL"),
        "timeout": {"default": 600, "fast": 600, "high": 3000},
        "threads": 4,
        "model": "TRELLIS.2",
        "frame": "trellis2_frame.py",
        "seed": 42,
        "max_faces": {"default": MAX_GEOMETRY, "fast": ATLAS_MAX_FACES, "high": ATLAS_MAX_FACES},
        # Steps None keeps the converted checkpoint's sampler steps and guidance.
        "quality": {
            "default": {"steps": None, "resolution": 512},
            "fast": {"steps": 6, "resolution": 512},
            "high": {"steps": None, "resolution": 1024},
        },
        "vertex_colors": True,
        "guides": True,
    },
}
QUALITIES = ("fast", "default", "high")
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_VIEWS = 5
# mlx-agent keeps the smallest bbox side at least two voxels of TRELLIS.2's 32³ sparse structure.
MAX_BOX_RATIO = 16
# The provider writes bbox endpoints at ±half the side length as float32 GLB positions.
MIN_BOX_SIZE = 2.0 ** -148
MAX_BOX_SIZE = float.fromhex("0x1.fffffep+128")


def tunable(prefix, name, default, quality="default", minimum=1, maximum=None):
    """``{prefix}_{QUALITY}_{NAME}``, else ``{prefix}_{NAME}``, else ``default``.

    A value parses as its default's type, an integer when the default is None: a number within the given bounds,
    or one lowercase option word.
    """
    kind = type(default) if isinstance(default, (str, float)) else int
    for key in (f"{prefix}_{quality.upper()}_{name}", f"{prefix}_{name}"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        if kind is str:
            if re.fullmatch(r"[a-z0-9][a-z0-9-]*", raw):
                return raw
            raise RuntimeError(f"{key} must be one lowercase option word")
        try:
            value = kind(raw)
        except ValueError:
            value = None
        if (value is None or (kind is float and not math.isfinite(value)) or value < minimum
                or (maximum is not None and value > maximum)):
            bounds = f"of at least {minimum}" if maximum is None else f"between {minimum} and {maximum}"
            raise RuntimeError(f"{key} must be {'a number' if kind is float else 'an integer'} {bounds}")
        return value
    return default


def tiered(value, quality):
    """The default for ``quality`` from a per-tier mapping, or the one default for every tier."""
    return value[quality] if isinstance(value, dict) else value


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


def mlx_options(settings, quality):
    """The configured mlx-agent options for ``quality`` and the face cap its result must meet."""
    prefix = settings["prefix"]
    options = []
    for option, default in settings["quality"][quality].items():
        value = tunable(prefix, option.upper().replace("-", "_"), default, quality)
        if value is not None:
            options += [f"--{option}", str(value)]
    seed = tunable(prefix, "SEED", settings["seed"], quality, minimum=0)
    max_faces = tunable(prefix, "MAX_FACES", tiered(settings["max_faces"], quality), quality, maximum=MAX_GEOMETRY)
    return [*options, "--seed", str(seed), "--max-faces", str(max_faces)], max_faces


def mlx_mesh(settings, configured, source, generated, env, timeout, deadline, quality, options, max_faces,
             views=(), guide=None, bbox=None):
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
        *options,
        *extra,
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
    prefix = settings["prefix"]
    quality = "default" if quality is None else quality
    if quality not in QUALITIES:
        raise ValueError("Quality must be fast, default or high")
    if quality != "default" and "quality" not in settings:
        raise ValueError("Quality tiers apply only to the triposg-mlx and trellis2-mlx providers")
    if quality not in settings.get("quality", {"default": ()}):
        raise ValueError("Quality high applies only to the trellis2-mlx provider")
    workspace = Path(workspace).resolve()
    source = inside(workspace, image, IMAGES, 16 * 1024 * 1024,
                    "Input image must be a workspace PNG, JPEG or WebP image of at most 16 MiB")
    views = list(views or ())
    if (views or guide is not None or bbox is not None) and not settings.get("guides"):
        raise ValueError("Views, guides and bbox apply only to the trellis2-mlx provider")
    if bbox is not None:
        if (guide is not None or not isinstance(bbox, (list, tuple)) or len(bbox) != 3
                or any(type(size) not in (int, float) or not MIN_BOX_SIZE <= size <= MAX_BOX_SIZE for size in bbox)
                or max(bbox) > MAX_BOX_RATIO * min(bbox)):
            raise ValueError(
                f"bbox takes three sizes with half-widths in the positive float32 range, "
                f"at most {MAX_BOX_RATIO} times apart, and no guide"
            )
        bbox = [float(size) for size in bbox]
    if len(views) > MAX_VIEWS:
        raise ValueError(f"Provide at most {MAX_VIEWS} views")
    views = [inside(workspace, view, IMAGES, 16 * 1024 * 1024,
                    "Each view must be a workspace PNG, JPEG or WebP image of at most 16 MiB") for view in views]
    if guide is not None:
        guide = inside(workspace, guide, {".glb"}, 64 * 1024 * 1024,
                       "The guide must be a workspace GLB of at most 64 MiB")
    target = destination(workspace, path, {".glb"})
    if resolution is not None and provider != "triposr":
        raise ValueError("Resolution applies only to the TripoSR provider")
    worker_options = {}
    for name, default in settings.get("worker_options", {}).items():
        if name == "resolution" and resolution is not None:
            worker_options[name] = resolution
        else:
            worker_options[name] = tunable(
                prefix, name.upper(), default, quality,
                minimum=0 if name in ("seed", "guidance") else 1,
                maximum=MAX_GEOMETRY if name == "max_faces" else None,
            )
    if provider == "triposr":
        resolved = worker_options["resolution"]
        if type(resolved) is not int or not 64 <= resolved <= 192:
            raise ValueError("Resolution must be between 64 and 192")
    timeout = tunable(prefix, "TIMEOUT", tiered(settings["timeout"], quality), quality)
    threads = tunable(prefix, "THREADS", settings["threads"], quality)
    if "quality" in settings:
        options, max_faces = mlx_options(settings, quality)
    configured = {}
    for suffix in settings["suffixes"]:
        key = f"{prefix}_{suffix}"
        value = os.environ.get(key)
        if not value or not Path(value).is_absolute() or not Path(value).exists():
            raise RuntimeError(f"Configure {key} with an existing absolute local path")
        configured[suffix] = value
    env = dict(
        os.environ,
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        OMP_NUM_THREADS=str(threads),
    )
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix=".cavi-generation-", dir=workspace) as temporary:
        generated = Path(temporary) / "mesh.glb"
        if "frame" in settings:
            report = mlx_mesh(settings, configured, source, generated, env, timeout, deadline, quality,
                              options, max_faces, views, guide, bbox)
        else:
            command = [
                configured["PYTHON"],
                str(Path(__file__).with_name(settings["worker"])),
                str(source),
                str(generated),
                json.dumps(worker_options),
            ]
            report = json.loads(run(command, env, timeout, deadline).stdout)
        if not generated.is_file():
            raise RuntimeError("Reconstruction did not produce a GLB")
        size = generated.stat().st_size
        if not size:
            raise RuntimeError("Reconstruction did not produce a GLB")
        if size > MAX_BYTES:
            raise RuntimeError(f"Reconstruction GLB is {size} bytes; maximum is {MAX_BYTES} bytes")
        if quality == "high":
            try:
                inspect_glb(temporary, generated.name)
            except ValueError as exc:
                raise RuntimeError(f"Reconstruction GLB cannot be imported: {exc}") from exc
        # Publish without replacing an existing destination, even if another writer won the race.
        os.link(generated, target)
    return {**report, "path": str(target), "bytes": target.stat().st_size}

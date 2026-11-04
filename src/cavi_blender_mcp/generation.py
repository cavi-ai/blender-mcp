"""Optional offline image-to-mesh worker; no downloads or account access."""

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

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
    },
}


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
            raise subprocess.TimeoutExpired(command, timeout)
        result = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=left, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Local reconstruction exceeded {timeout} seconds; no asset published"
        ) from exc
    if result.returncode:
        detail = (
            (describe and describe(result))
            or result.stderr.strip()
            or result.stdout.strip()
            or "No worker diagnostics"
        )
        raise RuntimeError(
            f"Local reconstruction failed (exit {result.returncode}): {detail[-2000:]}"
        )
    return result


def triposg_mlx(configured, source, generated, env, timeout, deadline):
    """Frame the image like the PyTorch provider, then run the mlx-agent mesh command."""
    framed = generated.with_name("framed.png")
    frame = Path(__file__).with_name("triposg_frame.py")
    run([configured["PYTHON"], str(frame), str(source), str(framed)], env, timeout, deadline)
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
        "--steps",
        "50",
        "--seed",
        "42",
        "--resolution",
        "512",
        "--max-faces",
        str(MLX_MAX_FACES),
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
            "provider": "TripoSG",
            "backend": data["backend"],
            "vertices": data["vertices"],
            "faces": data["faces"],
            "seconds": data["seconds"],
            "stage_seconds": data["stage_seconds"],
            "peak_memory_gb": data["peak_memory_gb"],
            "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("mlx-agent returned no usable mesh result") from exc
    if type(report["faces"]) is not int or not 0 < report["faces"] <= MLX_MAX_FACES:
        raise RuntimeError(f"Reconstruction must have between 1 and {MLX_MAX_FACES} faces")
    return report


def generate(workspace, image, path, resolution=None):
    provider = os.environ.get("CAVI_GENERATION_PROVIDER", "triposr")
    if provider not in PROVIDERS:
        raise ValueError("CAVI_GENERATION_PROVIDER must be triposr, triposg or triposg-mlx")
    settings = PROVIDERS[provider]
    workspace = Path(workspace).resolve()
    source = (workspace / image).resolve()
    if Path(image).is_absolute() or not source.is_relative_to(workspace):
        raise ValueError("Input image must remain inside the workspace")
    if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not source.is_file():
        raise ValueError("Provide an existing PNG, JPEG or WebP image")
    if not 0 < source.stat().st_size <= 16 * 1024 * 1024:
        raise ValueError("Input image must be at most 16 MiB")
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
        if provider == "triposg-mlx":
            report = triposg_mlx(configured, source, generated, env, timeout, deadline)
        else:
            command = [
                configured["PYTHON"],
                str(Path(__file__).with_name(settings["worker"])),
                str(source),
                str(generated),
                *arguments,
            ]
            report = json.loads(run(command, env, timeout, deadline).stdout)
        if not generated.is_file() or not 0 < generated.stat().st_size <= 64 * 1024 * 1024:
            raise RuntimeError("Reconstruction did not produce a bounded GLB")
        # Publish without replacing an existing destination, even if another writer won the race.
        os.link(generated, target)
    return {**report, "path": str(target), "bytes": target.stat().st_size}

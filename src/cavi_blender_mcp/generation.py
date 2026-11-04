"""Optional offline image-to-mesh worker; no downloads or account access."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .paths import destination

PROVIDERS = {
    "triposr": {"prefix": "CAVI_TRIPOSR", "worker": "neural_worker.py", "timeout": 180},
    "triposg": {"prefix": "CAVI_TRIPOSG", "worker": "triposg_worker.py", "timeout": 600},
}


def generate(workspace, image, path, resolution=None):
    provider = os.environ.get("CAVI_GENERATION_PROVIDER", "triposr")
    if provider not in PROVIDERS:
        raise ValueError("CAVI_GENERATION_PROVIDER must be triposr or triposg")
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
    if provider == "triposg":
        if resolution is not None:
            raise ValueError("Resolution applies only to the TripoSR provider")
        arguments = []
    else:
        resolution = 128 if resolution is None else resolution
        if type(resolution) is not int or not 64 <= resolution <= 192:
            raise ValueError("Resolution must be between 64 and 192")
        arguments = [str(resolution)]
    configured = {}
    for suffix in ("PYTHON", "SOURCE", "WEIGHTS"):
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
    with tempfile.TemporaryDirectory(prefix=".cavi-generation-", dir=workspace) as temporary:
        generated = Path(temporary) / "mesh.glb"
        command = [
            configured["PYTHON"],
            str(Path(__file__).with_name(settings["worker"])),
            str(source),
            str(generated),
            *arguments,
        ]
        try:
            result = subprocess.run(
                command, env=env, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Local reconstruction exceeded {timeout} seconds; no asset published"
            ) from exc
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "No worker diagnostics"
            raise RuntimeError(
                f"Local reconstruction failed (exit {result.returncode}): {detail[-2000:]}"
            )
        report = json.loads(result.stdout)
        if not generated.is_file() or not 0 < generated.stat().st_size <= 64 * 1024 * 1024:
            raise RuntimeError("Reconstruction did not produce a bounded GLB")
        # Publish without replacing an existing destination, even if another writer won the race.
        os.link(generated, target)
    return {**report, "path": str(target), "bytes": target.stat().st_size}

"""Optional offline text-to-panorama worker for world lighting; no downloads or account access."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from .generation import envelope_error, run
from .paths import destination

PREFIX = "CAVI_IMAGE_MLX"
SUFFIXES = ("PYTHON", "AGENT", "MODEL")
WIDTH, HEIGHT = 2048, 1024
# Columns crossfaded at the wrap so longitude stays one pixel per column.
BAND = 128
STEPS = {"default": 30, "fast": 12}
TIMEOUT = 1800
MAX_PROMPT = 1000
FRAMING = "seamless 360 degree equirectangular panorama, level horizon"


def panorama(workspace, prompt, path, quality=None):
    """A 2:1 equirectangular PNG of ``prompt`` from the local image model, made to wrap horizontally."""
    quality = "default" if quality is None else quality
    if quality not in STEPS:
        raise ValueError("Quality must be fast or default")
    if type(prompt) is not str or not 0 < len(prompt.strip()) <= MAX_PROMPT:
        raise ValueError(f"The prompt must be 1..{MAX_PROMPT} characters")
    workspace = Path(workspace).resolve()
    target = destination(workspace, path, {".png"})
    configured = {}
    for suffix in SUFFIXES:
        key = f"{PREFIX}_{suffix}"
        value = os.environ.get(key)
        if not value or not Path(value).is_absolute() or not Path(value).exists():
            raise RuntimeError(f"Configure {key} with an existing absolute local path")
        configured[suffix] = value
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
    deadline = time.monotonic() + TIMEOUT
    with tempfile.TemporaryDirectory(prefix=".cavi-panorama-", dir=workspace) as temporary:
        raw, wrapped = Path(temporary) / "raw.png", Path(temporary) / "panorama.png"
        agent_timeout = max(1, int(deadline - time.monotonic()) - 30)
        command = [configured["PYTHON"], configured["AGENT"], "convert", "generate", "--path", configured["MODEL"],
                   "--prompt", f"{prompt.strip()}, {FRAMING}", "--out", str(raw), "--width", str(WIDTH),
                   "--height", str(HEIGHT), "--steps", str(STEPS[quality]), "--seed", "42",
                   "--timeout", str(agent_timeout), "--json"]
        result = run(command, env, TIMEOUT, deadline, envelope_error)
        try:
            envelope = json.loads(result.stdout)
            if envelope["status"] != "ok":
                raise ValueError(envelope["status"])
            seconds = envelope["data"]["seconds"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("mlx-agent returned no usable image result") from exc
        seam = Path(__file__).with_name("panorama_seam.py")
        run([configured["PYTHON"], str(seam), str(raw), str(wrapped), str(BAND)], env, TIMEOUT, deadline)
        if not wrapped.is_file() or not 0 < wrapped.stat().st_size <= 64 * 1024 * 1024:
            raise RuntimeError("Panorama generation did not produce a bounded PNG")
        os.link(wrapped, target)
    return {"provider": "mlx-image", "width": WIDTH, "height": HEIGHT, "steps": STEPS[quality],
            "quality": quality, "seam_band": BAND, "seconds": seconds,
            "prompt_sha256": hashlib.sha256(prompt.strip().encode()).hexdigest(),
            "path": str(target), "bytes": target.stat().st_size}

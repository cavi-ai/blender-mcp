"""Optional offline text-to-panorama worker for world lighting; no downloads or account access."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from .generation import envelope_error, run, tunable
from .paths import destination

PREFIX = "CAVI_IMAGE_MLX"
SUFFIXES = ("PYTHON", "AGENT", "MODEL")
# Built-in defaults, each read from CAVI_IMAGE_MLX_<QUALITY>_<NAME>, then CAVI_IMAGE_MLX_<NAME>.
# The height is half the width: a 2:1 equirectangular image.
WIDTH = 2048
# Columns crossfaded at the wrap (SEAM_BAND) so longitude stays one pixel per column.
BAND = 128
# Scene-linear value that 8-bit white reaches in an EXR panorama, four stops above display white.
WHITE = 16.0
MAX_EXR_WHITE = 65_504  # Largest finite half-float value.
STEPS = {"default": 30, "fast": 12}
TIMEOUT = 1800
SEED = 42
MAX_PROMPT = 1000
FRAMING = "seamless 360 degree equirectangular panorama, level horizon"


def panorama(workspace, prompt, path, quality=None):
    """A 2:1 equirectangular PNG or half-float EXR of ``prompt`` from the local image model.

    The image wraps horizontally. An EXR holds scene-linear values whose 8-bit white reaches the configured white.
    """
    quality = "default" if quality is None else quality
    if quality not in STEPS:
        raise ValueError("Quality must be fast or default")
    if type(prompt) is not str or not 0 < len(prompt.strip()) <= MAX_PROMPT:
        raise ValueError(f"The prompt must be 1..{MAX_PROMPT} characters")
    width = tunable(PREFIX, "WIDTH", WIDTH, quality, minimum=2)
    band = tunable(PREFIX, "SEAM_BAND", BAND, quality)
    if width % 2 or band >= width // 2:
        raise RuntimeError(f"{PREFIX}_WIDTH must be even and {PREFIX}_SEAM_BAND narrower than half of it")
    height = width // 2
    steps = tunable(PREFIX, "STEPS", STEPS[quality], quality)
    seed = tunable(PREFIX, "SEED", SEED, quality, minimum=0)
    timeout = tunable(PREFIX, "TIMEOUT", TIMEOUT, quality)
    workspace = Path(workspace).resolve()
    target = destination(workspace, path, {".png", ".exr"})
    extension = target.suffix.lower()
    white = tunable(PREFIX, "WHITE", WHITE, quality, maximum=MAX_EXR_WHITE) if extension == ".exr" else WHITE
    configured = {}
    for suffix in SUFFIXES:
        key = f"{PREFIX}_{suffix}"
        value = os.environ.get(key)
        if not value or not Path(value).is_absolute() or not Path(value).exists():
            raise RuntimeError(f"Configure {key} with an existing absolute local path")
        configured[suffix] = value
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix=".cavi-panorama-", dir=workspace) as temporary:
        raw, wrapped = Path(temporary) / "raw.png", Path(temporary) / f"panorama{extension}"
        agent_timeout = max(1, int(deadline - time.monotonic()) - 30)
        command = [configured["PYTHON"], configured["AGENT"], "convert", "generate", "--path", configured["MODEL"],
                   "--prompt", f"{prompt.strip()}, {FRAMING}", "--out", str(raw), "--width", str(width),
                   "--height", str(height), "--steps", str(steps), "--seed", str(seed),
                   "--timeout", str(agent_timeout), "--json"]
        result = run(command, env, timeout, deadline, envelope_error)
        try:
            envelope = json.loads(result.stdout)
            if envelope["status"] != "ok":
                raise ValueError(envelope["status"])
            seconds = envelope["data"]["seconds"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("mlx-agent returned no usable image result") from exc
        seam = Path(__file__).with_name("panorama_seam.py")
        run([configured["PYTHON"], str(seam), str(raw), str(wrapped), str(band), str(white)],
            env, timeout, deadline)
        if not wrapped.is_file() or not 0 < wrapped.stat().st_size <= 64 * 1024 * 1024:
            raise RuntimeError("Panorama generation did not produce a bounded image")
        os.link(wrapped, target)
    report = {"provider": "mlx-image", "width": width, "height": height, "steps": steps,
              "quality": quality, "seam_band": band, "seconds": seconds,
              "prompt_sha256": hashlib.sha256(prompt.strip().encode()).hexdigest(),
              "path": str(target), "bytes": target.stat().st_size}
    if extension == ".exr":
        report["white"] = white
    return report

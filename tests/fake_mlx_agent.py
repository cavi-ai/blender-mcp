"""Stands in for `mlx-agent convert mesh`: enforces the command contract and answers with its envelope."""

import argparse
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

PNG_SIGNATURE = bytes([0x89]) + b"PNG\r\n" + bytes([0x1A]) + b"\n"

parser = argparse.ArgumentParser()
parser.add_argument("command")
parser.add_argument("kind")
parser.add_argument("--path", required=True)
parser.add_argument("--image", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--steps", type=int)
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--resolution", type=int, required=True)
parser.add_argument("--max-faces", type=int, required=True)
parser.add_argument("--denoiser-cache", choices=("off", "adaptive"), default="off")
parser.add_argument("--view", action="append", default=[])
parser.add_argument("--guide")
parser.add_argument("--bbox", type=float, nargs=3)
parser.add_argument("--timeout", type=int, required=True)
parser.add_argument("--json", action="store_true", required=True)
arguments = parser.parse_args()
mode = os.environ["FAKE_AGENT_MODE"]
# TripoSG takes fixed steps and an RGB frame; TRELLIS.2 keeps its own steps and needs alpha.
trellis = os.environ.get("FAKE_AGENT_MODEL") == "trellis2"
# Sampler steps, grid resolution and denoiser cache each quality tier must send.
TIERS = {
    (False, "default"): (50, 512, "off"),
    (False, "fast"): (25, 256, "adaptive"),
    (True, "default"): (None, 512, "off"),
    (True, "fast"): (6, 512, "off"),
    (True, "high"): (None, 1024, "off"),
}
tier = TIERS[trellis, os.environ.get("FAKE_AGENT_QUALITY", "default")]
record = Path(os.environ["FAKE_AGENT_RECORD"])
out = Path(arguments.out)


def reply(status, data=None, code="", exit_code=0):
    envelope = {"operation": "convert-mesh", "status": status, "data": data or {}, "warnings": []}
    if code:
        message = os.environ.get("FAKE_AGENT_MESSAGE", "refused")
        envelope["error"] = {"code": code, "message": message}
    print(json.dumps(envelope, indent=2))
    sys.exit(exit_code)


def framed(path):
    data = Path(path).read_bytes()
    return (data[:8] == PNG_SIGNATURE and struct.unpack(">II", data[16:24]) == (512, 512)
            and data[25] == (6 if trellis else 2))


valid = (
    (arguments.command, arguments.kind) == ("convert", "mesh")
    and Path(arguments.path).is_dir()
    and framed(arguments.image)
    and all(trellis and framed(view) for view in arguments.view)
    and (arguments.guide is None or (trellis and Path(arguments.guide).suffix == ".glb"
                                     and Path(arguments.guide).is_file()))
    and (arguments.bbox is None or (trellis and arguments.guide is None))
    and out.suffix == ".glb"
    and not out.exists()
    and out.parent.is_dir()
    and (arguments.steps, arguments.resolution, arguments.denoiser_cache) == tier
    and arguments.seed == 42
    and arguments.max_faces == (166666 if trellis and os.environ.get("FAKE_AGENT_QUALITY") == "fast" else 500000)
    and 1 <= arguments.timeout <= 600
)
if not valid:
    reply("error", code="invalid_arguments", exit_code=2)
shutil.copy(arguments.image, record / "image.png")
for index, view in enumerate(arguments.view):
    shutil.copy(view, record / f"view-{index}.png")
if arguments.guide:
    shutil.copy(arguments.guide, record / "guide.glb")
if mode == "hang":
    time.sleep(60)
if mode == "crash":
    print("backend crashed", file=sys.stderr)
    sys.exit(3)
if mode == "garbage":
    print("not an envelope")
    sys.exit(0)
if mode == "error":
    out.write_bytes(b"partial-glb")
    reply("error", code=os.environ["FAKE_AGENT_CODE"], exit_code=2)
glb = b"glTF" + struct.pack("<II", 2, 28) + bytes(16)
if mode != "missing":
    out.write_bytes(b"" if mode == "empty" else glb)
    if mode == "oversized_file":
        with out.open("r+b") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
    (record / "mesh.glb").write_bytes(glb)
if mode == "race":
    (out.parent.parent / "mesh.glb").write_bytes(b"other-writer")
data = {
    "path": str(out),
    "seconds": 143.536,
    "steps": 12 if trellis else 50,
    "seed": 42,
    "resolution": 512,
    "vertices": 249896,
    "faces": (arguments.max_faces + 1 if mode == "oversized" else arguments.max_faces - 10),
    "queries": [16777216, 12473832],
    "stage_seconds": {"load": 0.864, "sampling": 61.804, "decode_refine": 33.015},
    "peak_memory_gb": 10.301,
    "load_seconds": 0.864,
    "schema": "mesh/1",
    "backend": "mlx-3d",
    "model": arguments.path,
}
if trellis and mode != "unflagged":
    data["vertex_colors"] = mode != "uncolored"
if trellis:
    data.update(views=1 + len(arguments.view), guided=arguments.guide is not None,
                bbox=None if mode == "unboxed" else arguments.bbox)
reply("ok", data)

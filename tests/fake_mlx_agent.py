"""Stands in for `mlx-agent convert mesh`: enforces the command contract and answers with its envelope."""

import argparse
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

from test_importing import write_glb

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
quality = os.environ.get("FAKE_AGENT_QUALITY", "default")
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
tier = TIERS[trellis, quality]
# The built-in defaults each run must send; FAKE_AGENT_EXPECT names configured values instead.
expected = {
    "steps": tier[0], "resolution": tier[1], "denoiser_cache": tier[2], "seed": 42,
    "max_faces": None if quality == "high" else (166666 if trellis and quality == "fast" else 500000),
    "timeout": 3000 if quality == "high" else 600,
    **json.loads(os.environ.get("FAKE_AGENT_EXPECT", "{}")),
}
record = Path(os.environ["FAKE_AGENT_RECORD"])
(record / "arguments.json").write_text(json.dumps(vars(arguments)))
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
    and [getattr(arguments, name) for name in ("steps", "resolution", "denoiser_cache", "seed")]
    == [expected[name] for name in ("steps", "resolution", "denoiser_cache", "seed")]
    and expected["max_faces"] in (None, arguments.max_faces)
    and 1 <= arguments.timeout <= expected["timeout"]
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
faces = arguments.max_faces - 10
glb = b"glTF" + struct.pack("<II", 2, 28) + bytes(16)
if mode != "missing":
    if mode == "empty":
        out.write_bytes(b"")
    elif quality == "high":
        # An expanded mesh stores three positions per face, just like atlas export.
        faces = arguments.max_faces
        exported_faces = 166_667 if mode == "over_budget_glb" else faces
        binary = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0) * exported_faces
        document = {
            "asset": {"version": "2.0"},
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": [{"buffer": 0, "byteLength": len(binary)}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3 * exported_faces,
                           "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
            "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0,
        }
        write_glb(out, document, binary)
    else:
        out.write_bytes(glb)
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
    "faces": arguments.max_faces + 1 if mode == "oversized" else faces,
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

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
parser.add_argument("--steps", type=int, required=True)
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--resolution", type=int, required=True)
parser.add_argument("--max-faces", type=int, required=True)
parser.add_argument("--timeout", type=int, required=True)
parser.add_argument("--json", action="store_true", required=True)
arguments = parser.parse_args()
mode = os.environ["FAKE_AGENT_MODE"]
record = Path(os.environ["FAKE_AGENT_RECORD"])
out = Path(arguments.out)


def reply(status, data=None, code="", exit_code=0):
    envelope = {"operation": "convert-mesh", "status": status, "data": data or {}, "warnings": []}
    if code:
        message = os.environ.get("FAKE_AGENT_MESSAGE", "refused")
        envelope["error"] = {"code": code, "message": message}
    print(json.dumps(envelope, indent=2))
    sys.exit(exit_code)


image = Path(arguments.image).read_bytes()
valid = (
    (arguments.command, arguments.kind) == ("convert", "mesh")
    and Path(arguments.path).is_dir()
    and image[:8] == PNG_SIGNATURE
    and struct.unpack(">II", image[16:24]) == (512, 512)
    and out.suffix == ".glb"
    and not out.exists()
    and out.parent.is_dir()
    and (arguments.steps, arguments.seed, arguments.resolution) == (50, 42, 512)
    and arguments.max_faces == 500000
    and 1 <= arguments.timeout <= 600
)
if not valid:
    reply("error", code="invalid_arguments", exit_code=2)
shutil.copy(arguments.image, record / "image.png")
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
    out.write_bytes(glb)
    (record / "mesh.glb").write_bytes(glb)
if mode == "race":
    (out.parent.parent / "mesh.glb").write_bytes(b"other-writer")
reply(
    "ok",
    {
        "path": str(out),
        "seconds": 143.536,
        "steps": 50,
        "seed": 42,
        "resolution": 512,
        "vertices": 249896,
        "faces": 500001 if mode == "oversized" else 499990,
        "queries": [16777216, 12473832],
        "stage_seconds": {"load": 0.864, "sampling": 61.804, "decode_refine": 33.015},
        "peak_memory_gb": 10.301,
        "load_seconds": 0.864,
        "schema": "mesh/1",
        "backend": "mlx-3d",
        "model": arguments.path,
    },
)

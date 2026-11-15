"""Stands in for `mlx-agent convert generate`: checks the panorama request and writes a left-to-right ramp."""

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("command")
parser.add_argument("kind")
for flag in ("--path", "--prompt", "--out"):
    parser.add_argument(flag, required=True)
for flag in ("--width", "--height", "--steps", "--seed", "--timeout"):
    parser.add_argument(flag, type=int, required=True)
parser.add_argument("--json", action="store_true", required=True)
arguments = parser.parse_args()
record = Path(os.environ["FAKE_IMAGE_RECORD"])
(record / "request.json").write_text(json.dumps(vars(arguments)))
out = Path(arguments.out)
valid = ((arguments.command, arguments.kind) == ("convert", "generate") and Path(arguments.path).is_dir()
         and out.suffix == ".png" and not out.exists() and (arguments.width, arguments.height) == (2048, 1024)
         and arguments.seed == 42 and 1 <= arguments.timeout <= 1800)
if not valid or os.environ.get("FAKE_IMAGE_MODE") == "error":
    print(json.dumps({"status": "error", "data": {}, "error": {"code": "invalid_arguments", "message": "refused"}}))
    sys.exit(2)
ramp = Image.linear_gradient("L").rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
ramp.resize((arguments.width, arguments.height)).convert("RGB").save(out, format="PNG")
print(json.dumps({"status": "ok", "data": {"path": str(out), "seconds": 12.5}}))

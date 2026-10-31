"""File boundaries shared by the MCP client and Blender bridge."""

import os
from pathlib import Path


def environment_path(name: str, default: Path | str) -> Path:
    value = os.environ.get(name)
    return Path(value if value is not None and value.strip() else default).expanduser()


def destination(workspace: Path, name: str, extensions: set[str]) -> Path:
    root = workspace.expanduser().resolve(strict=True)
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Output must stay inside the configured workspace")
    if path.suffix.lower() not in extensions:
        raise ValueError(f"Expected extension in {sorted(extensions)}")
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path.name}")
    if not path.parent.is_dir():
        raise ValueError("Output parent directory must exist")
    return path

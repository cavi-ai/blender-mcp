"""File boundaries shared by the MCP client and Blender bridge."""

from pathlib import Path


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

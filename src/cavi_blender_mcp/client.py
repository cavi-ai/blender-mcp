"""Authenticated loopback transport. Mutations are never retried."""

import http.client
import json
import os
import stat
import uuid
from pathlib import Path

OPERATIONS = frozenset(
    {
        "scene_info",
        "object_info",
        "inspect_mesh_quality",
        "create_primitive",
        "create_mesh",
        "import_mesh",
        "transform_object",
        "set_color",
        "add_modifier",
        "shade_mesh",
        "unwrap_mesh",
        "export_mesh",
        "export_instances",
        "save_project",
        "render_preview",
        "runtime_status",
        "runtime_restart",
        "session_control",
        "owned_edit",
        "assign_material",
        "decimate_to",
        "remesh_quad",
        "lod_chain",
        "lightmap_uv",
        "texel_density",
        "collision",
        "cleanup_mesh",
        "apply_transforms",
        "set_origin",
        "snap_to_grid",
        "rename_object",
        "add_socket",
        "export_asset",
        "review_sheet",
        "scatter",
    }
)
SLOW_OPERATIONS = frozenset(
    {"import_mesh", "export_mesh", "export_instances", "add_modifier", "render_preview",
     "save_project", "decimate_to", "lightmap_uv", "texel_density", "collision", "cleanup_mesh",
     "export_asset", "review_sheet", "scatter"}
)
DEFAULT_TIMEOUT = 60
SLOW_TIMEOUT = 300
MAX_TIMEOUT = 600
LONG_OPERATIONS = frozenset({"remesh_quad", "lod_chain"})
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class BridgeError(ConnectionError):
    """A bridge protocol failure whose diagnostic must be preserved."""


class BridgeOperationError(RuntimeError):
    """A live bridge executed or refused the request and reported an error."""


def default_connection() -> Path:
    return Path(
        os.environ.get(
            "CAVI_BLENDER_CONNECTION", Path.home() / ".cavi/blender-mcp/connection.json"
        )
    )


def operation_timeout(operation, params):
    inner = params.get("operation") if operation == "owned_edit" else operation
    if inner in LONG_OPERATIONS:
        return MAX_TIMEOUT
    return SLOW_TIMEOUT if inner in SLOW_OPERATIONS else DEFAULT_TIMEOUT


def process_alive(pid):
    if os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class BridgeClient:
    def __init__(self, config: Path | None = None):
        self.config = config or default_connection()

    def read_config(self):
        try:
            fd = os.open(self.config, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError as exc:
            raise ConnectionError(
                "Blender bridge is not running; start Blender with the bridge"
            ) from exc
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (
                os.name != "nt" and (info.st_mode & 0o077 or info.st_uid != os.getuid())
            ):
                raise PermissionError("Connection file must be private and owned by this user")
            config = json.load(stream)
        if not isinstance(config, dict):
            config = {}
        pid = config.get("pid")
        if pid is not None and (type(pid) is not int or pid <= 0):
            raise ValueError("Invalid bridge connection file")
        if pid is not None and not process_alive(pid):
            self.discard(info)
            raise ConnectionError(
                "Blender bridge is not running; removed a stale connection file"
            ) from FileNotFoundError(str(self.config))
        return config

    def discard(self, info):
        try:
            current = os.stat(self.config, follow_symlinks=False)
            if (current.st_ino, current.st_dev) == (info.st_ino, info.st_dev):
                os.unlink(self.config)
        except FileNotFoundError:
            pass

    def call(self, operation: str, params: dict | None = None, timeout: float | None = None):
        if operation not in OPERATIONS:
            raise ValueError(f"Unknown operation: {operation}")
        params = params or {}
        timeout = min(timeout or operation_timeout(operation, params), MAX_TIMEOUT)
        config = self.read_config()
        if config.get("host") != "127.0.0.1":
            raise ValueError("Bridge must use IPv4 loopback")
        port, token = config.get("port"), config.get("token")
        if (
            type(port) is not int
            or not 1 <= port <= 65535
            or not isinstance(token, str)
            or len(token) < 32
        ):
            raise ValueError("Invalid bridge connection file")
        request_id = uuid.uuid4().hex
        payload = json.dumps(
            {"id": request_id, "operation": operation, "params": params, "timeout": timeout}
        ).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise ValueError(f"Request exceeds {MAX_REQUEST_BYTES} bytes")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout + 5)
        try:
            connection.request(
                "POST",
                "/rpc",
                payload,
                {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise BridgeError("Bridge response exceeds size limit")
            if response.status != 200:
                raise BridgeError(
                    f"Bridge HTTP {response.status}: {error_message(body)}; request was not retried"
                )
            result = json.loads(body)
            if result.get("id") != request_id:
                raise BridgeError("Bridge response ID mismatch")
            if "error" in result:
                raise BridgeOperationError(result["error"])
            return result["result"]
        except BridgeError:
            raise
        except (TimeoutError, OSError) as exc:
            raise ConnectionError(
                "Bridge connection failed; outcome may be unknown. Do not retry a mutation without inspecting the scene."
            ) from exc
        finally:
            connection.close()


def error_message(body):
    try:
        message = json.loads(body).get("error")
    except (ValueError, AttributeError):
        message = None
    return message if isinstance(message, str) and message else "no diagnostic"

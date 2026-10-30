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
        "create_primitive",
        "create_mesh",
        "import_mesh",
        "transform_object",
        "set_color",
        "add_modifier",
        "shade_mesh",
        "unwrap_mesh",
        "export_mesh",
        "save_project",
        "render_preview",
        "runtime_status",
        "runtime_restart",
        "session_control",
        "owned_edit",
        "assign_material",
    }
)


class BridgeError(ConnectionError):
    """A bridge protocol failure whose diagnostic must be preserved."""


class BridgeClient:
    def __init__(self, config: Path | None = None):
        self.config = config or Path(
            os.environ.get(
                "CAVI_BLENDER_CONNECTION", Path.home() / ".cavi/blender-mcp/connection.json"
            )
        )

    def call(self, operation: str, params: dict | None = None):
        if operation not in OPERATIONS:
            raise ValueError(f"Unknown operation: {operation}")
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
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=65)
        try:
            connection.request(
                "POST",
                "/rpc",
                json.dumps(
                    {
                        "id": request_id,
                        "operation": operation,
                        "params": params or {},
                    }
                ),
                {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise BridgeError("Bridge response exceeds size limit")
            if response.status != 200:
                raise BridgeError(f"Bridge HTTP {response.status}; request was not retried")
            result = json.loads(body)
            if result.get("id") != request_id:
                raise BridgeError("Bridge response ID mismatch")
            if "error" in result:
                raise RuntimeError(result["error"])
            return result["result"]
        except BridgeError:
            raise
        except (TimeoutError, OSError) as exc:
            raise ConnectionError(
                "Bridge connection failed; outcome may be unknown. Do not retry a mutation without inspecting the scene."
            ) from exc
        finally:
            connection.close()

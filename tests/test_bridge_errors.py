import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from cavi_blender_mcp.client import MAX_REQUEST_BYTES, BridgeClient


def dead_pid():
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def max_create_mesh_request():
    coordinate = -1.2345678901234567e-05
    vertices = [[coordinate] * 3 for _ in range(10000)]
    faces = [[9999, 9998, 9997, 9996, 9995] for _ in range(20000)]
    return {"operation": "create_mesh",
            "params": {"name": "x" * 63, "vertices": vertices, "faces": faces,
                       "lease_id": "y" * 64}}


class Server:
    def __init__(self, test, status=200, body=None):
        self.received = []
        received = self.received

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(request)
                payload = body if body is not None else {"id": request["id"], "result": {}}
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        worker.start()
        test.addCleanup(worker.join)
        test.addCleanup(self.http.server_close)
        test.addCleanup(self.http.shutdown)


def connection(folder, **fields):
    path = Path(folder) / "connection.json"
    path.write_text(json.dumps({"host": "127.0.0.1", "token": "x" * 64, **fields}))
    path.chmod(0o600)
    return path


class BridgeErrorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = temp.name

    def test_error_body_is_surfaced(self):
        for status, message in [(503, "Bridge queue is full; request was not executed"),
                                (504, "Request was not started within 60s"),
                                (413, "Request exceeds 8388608 bytes")]:
            server = Server(self, status, {"id": None, "error": message})
            config = connection(self.folder, port=server.http.server_port)
            with self.subTest(status=status), self.assertRaises(ConnectionError) as caught:
                BridgeClient(config).call("create_primitive", {"name": "P", "kind": "cube"})
            self.assertIn(f"HTTP {status}: {message}", str(caught.exception))
            self.assertEqual(len(server.received), 1)

    def test_operation_timeout_is_sent_and_bounds_http_wait(self):
        server = Server(self)
        config = connection(self.folder, port=server.http.server_port)
        timeouts = []
        real = __import__("http.client").client.HTTPConnection

        def spy(host, port, timeout):
            timeouts.append(timeout)
            return real(host, port, timeout=timeout)

        with patch("cavi_blender_mcp.client.http.client.HTTPConnection", side_effect=spy):
            client = BridgeClient(config)
            client.call("scene_info")
            client.call("owned_edit", {"operation": "export_mesh", "params": {}})
            client.call("scene_info", timeout=5000)
        self.assertEqual([r["timeout"] for r in server.received], [60, 300, 600])
        self.assertEqual(timeouts, [65, 305, 605])

    def test_maximal_create_mesh_payload_fits_request_cap(self):
        request = {"id": "0" * 32, **max_create_mesh_request(), "timeout": 60}
        size = len(json.dumps(request).encode())
        self.assertGreater(size, 1_048_576)
        self.assertLess(size, MAX_REQUEST_BYTES)
        server = Server(self)
        config = connection(self.folder, port=server.http.server_port)
        BridgeClient(config).call("create_mesh", max_create_mesh_request()["params"])
        self.assertEqual(len(server.received[0]["params"]["faces"]), 20000)

    @unittest.skipIf(os.name == "nt", "POSIX pid check")
    def test_stale_pid_connection_is_offline_and_removed(self):
        config = connection(self.folder, port=1, pid=dead_pid())
        with self.assertRaisesRegex(ConnectionError, "not running") as caught:
            BridgeClient(config).call("scene_info")
        self.assertIsInstance(caught.exception.__cause__, FileNotFoundError)
        self.assertFalse(config.exists())

    @unittest.skipIf(os.name == "nt", "POSIX pid check")
    def test_runtime_start_replaces_stale_connection(self):
        from types import SimpleNamespace

        from cavi_blender_mcp.runtime import start_runtime

        root = Path(self.folder).resolve()
        binary = root / "blender"
        binary.write_text("binary")
        binary.chmod(0o700)
        config = connection(root, port=1, pid=dead_pid())
        calls = []
        with (
            patch.dict(os.environ, {"CAVI_BLENDER_BIN": str(binary),
                                   "CAVI_BLENDER_WORKSPACE": str(root / "assets"),
                                   "CAVI_BLENDER_CONNECTION": str(config)}),
            patch("cavi_blender_mcp.runtime.subprocess.Popen",
                  side_effect=lambda command, **kw: calls.append(command) or
                  SimpleNamespace(pid=1)),
        ):
            result = start_runtime(background=True)
        self.assertTrue(result["launch_requested"])
        self.assertEqual(calls[0][1], "--background")
        self.assertFalse(config.exists())

    def test_live_pid_is_still_contacted(self):
        server = Server(self)
        config = connection(self.folder, port=server.http.server_port, pid=os.getpid())
        self.assertEqual(BridgeClient(config).call("scene_info"), {})


if __name__ == "__main__":
    unittest.main()

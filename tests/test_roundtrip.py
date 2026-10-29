import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from cavi_blender_mcp.client import BridgeClient


class RoundtripTests(unittest.TestCase):
    def serve(self, reply_id=True, status=200):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.headers["Authorization"], request))
                self.send_response(status)
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"id": request["id"] if reply_id else "wrong", "result": {"objects": []}}
                    ).encode()
                )

        server = HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = Path(temp.name) / "connection.json"
        config.write_text(
            json.dumps({"host": "127.0.0.1", "port": server.server_port, "token": "x" * 64})
        )
        config.chmod(0o600)
        return BridgeClient(config), received

    def test_authenticated_request_and_correlated_response(self):
        client, received = self.serve()
        self.assertEqual(client.call("scene_info"), {"objects": []})
        self.assertEqual(received[0][0], "Bearer " + "x" * 64)
        self.assertEqual(received[0][1]["operation"], "scene_info")

    def test_response_id_mismatch_is_rejected(self):
        client, _ = self.serve(reply_id=False)
        with self.assertRaisesRegex(ConnectionError, "ID mismatch"):
            client.call("scene_info")

    def test_failed_mutation_is_never_retried(self):
        client, received = self.serve(status=503)
        with self.assertRaises(ConnectionError):
            client.call("create_primitive", {"name": "Prop", "kind": "cube"})
        self.assertEqual(len(received), 1)

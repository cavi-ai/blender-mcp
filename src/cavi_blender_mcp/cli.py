"""Command-line control of the authenticated Blender bridge."""

import argparse
import json

from .client import BridgeClient


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cavi-blender-mcp")
    commands = parser.add_subparsers(dest="command", required=True)
    runtime = commands.add_parser("runtime", help="Inspect or restart the running Blender bridge")
    runtime.add_argument("action", choices=("status", "restart"))
    args = parser.parse_args(argv)
    try:
        client = BridgeClient()
        restarted = client.call("runtime_restart") if args.action == "restart" else None
        result = client.call("runtime_status")
        if restarted and result["generation"] != restarted["generation"]:
            raise RuntimeError("Bridge changed again after restart; inspect runtime status")
        if restarted:
            result["restarted"] = True
        print(json.dumps(result))
        return 0
    except (ConnectionError, OSError, RuntimeError, ValueError) as exc:
        reason = str(exc)
        if "Unknown operation: runtime_" in reason:
            reason = "Reopen the dedicated Blender session with the updated start_bridge.py once"
        print(json.dumps({"connected": False, "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line control of the authenticated Blender bridge."""

import argparse
import json

from .bridge_contract import compatibility
from .client import BridgeClient
from .runtime import start_runtime


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cavi-blender-mcp")
    commands = parser.add_subparsers(dest="command", required=True)
    runtime = commands.add_parser("runtime", help="Start, inspect or control the Blender bridge")
    runtime.add_argument("action", choices=("start", "status", "restart", "open"))
    runtime.add_argument("--project", help="Existing workspace .blend for start or open")
    runtime.add_argument("--lease-id", help="Current edit lease, required for restart/open")
    runtime.add_argument("--expected-sha256", help="Expected saved source hash (runtime open only)")
    runtime.add_argument("--background", action="store_true",
                         help="Start headless Blender (runtime start only)")
    args = parser.parse_args(argv)
    if args.project is not None and args.action not in {"start", "open"}:
        parser.error("--project is only supported by runtime start/open")
    if args.expected_sha256 is not None and args.action != 'open':
        parser.error('--expected-sha256 is only supported by runtime open')
    if args.action == 'open' and (not args.project or not args.lease_id):
        parser.error('runtime open requires --project and --lease-id')
    if args.background and args.action != "start":
        parser.error("--background is only supported by runtime start")
    try:
        if args.action == "start":
            print(json.dumps(start_runtime(args.project, args.background)))
            return 0
        client = BridgeClient()
        if args.action == 'open':
            print(json.dumps(client.call('open_project', {'path': args.project,
                'lease_id': args.lease_id, 'expected_sha256': args.expected_sha256})))
            return 0
        restarted = (
            client.call("runtime_restart", {"lease_id": args.lease_id})
            if args.action == "restart" else None
        )
        result = client.call("runtime_status")
        result['bridge_compatibility'] = compatibility(result.get('bridge'))
        if restarted and result["generation"] != restarted["generation"]:
            raise RuntimeError("Bridge changed again after restart; inspect runtime status")
        if restarted:
            result["restarted"] = True
        print(json.dumps(result))
        return 0 if result['bridge_compatibility']['matches'] else 1
    except (ConnectionError, OSError, RuntimeError, ValueError) as exc:
        reason = str(exc)
        if "Unknown operation: runtime_" in reason:
            reason = "Reopen the dedicated Blender session with the updated start_bridge.py once"
        print(json.dumps({"connected": False, "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line control of the authenticated Blender bridge."""

import argparse
import json
import subprocess

from .bridge_contract import runtime_report
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
    extension = commands.add_parser(
        "extension", help="Build or install the Blender extension that starts the bridge")
    extension.add_argument("action", choices=("build", "install"))
    extension.add_argument("--output", default=".",
                           help="Folder for the built archive (extension build only)")
    args = parser.parse_args(argv)
    if args.command == "extension":
        return extension_command(args)
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
        result = runtime_report(client, args.action == "restart", args.lease_id)
        print(json.dumps(result))
        return 0 if result['bridge_compatibility']['matches'] else 1
    except (ConnectionError, OSError, RuntimeError, ValueError) as exc:
        reason = str(exc)
        if "Unknown operation: runtime_" in reason:
            reason = "Reopen the dedicated Blender session with the updated start_bridge.py once"
        print(json.dumps({"connected": False, "reason": reason}))
        return 1


def extension_command(args):
    from . import extension

    try:
        if args.action == "build":
            result = {"archive": str(extension.build(args.output)), "version": extension.version()}
        else:
            result = extension.install()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"reason": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

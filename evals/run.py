"""Run deterministic evaluations over the real stdio MCP surface."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
APP = "blender"
MODES = ["protocol", "native"]


def pointer(value, path):
    for key in path.strip("/").split("/"):
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


async def exercise(mode, env, workspace, adapter=None, include_model=False):
    corpus = json.loads((ROOT / "evals/cases.json").read_text())
    if len({case["id"] for case in corpus}) != len(corpus):
        raise ValueError("Corpus case IDs must be unique")
    selected = [
        case
        for case in corpus
        if mode in case["modes"] or (include_model and "model" in case["modes"])
    ]
    results = []
    params = StdioServerParameters(
        command=sys.executable, args=["-m", f"cavi_{APP}_mcp.server"], env=env
    )
    async with (
        stdio_client(params) as (reader, writer),
        ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=210)) as session,
    ):
        await session.initialize()
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        expected = {case["tool"] for case in corpus}
        if set(tools) != expected:
            raise AssertionError(f"Tool coverage drift: listed={set(tools)}, corpus={expected}")
        for tool in tools.values():
            covered = [case for case in corpus if case["tool"] == tool.name]
            if not any(case["kind"] == "success" for case in covered):
                raise AssertionError(f"Missing success coverage: {tool.name}")
            if tool.inputSchema.get("required") and not any(
                case["kind"] == "invalid" for case in covered
            ):
                raise AssertionError(f"Missing invalid-input coverage: {tool.name}")
            if not (tool.annotations and tool.annotations.readOnlyHint) and not any(
                case["kind"] == "safety" for case in covered
            ):
                raise AssertionError(f"Missing safety coverage: {tool.name}")
        lease_id = None
        for case in selected:
            try:
                if case.get("setup"):
                    if adapter is None:
                        raise AssertionError("Case requires the explicitly simulated adapter")
                    adapter.setup(case["setup"])
                protected = {
                    p: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in list(workspace.rglob("*"))
                    + list((workspace.parent / "outside").rglob("*"))
                    if p.is_file()
                }

                arguments = dict(case["arguments"])
                if mode != "protocol":
                    lease_free = (case["tool"] in {"session_control", "render_preview", "review_sheet"}
                                  or arguments.get("action") == "generate")
                    needs_lease = (not lease_free
                                   and not tools[case["tool"]].annotations.readOnlyHint
                                   and not case.get("without_lease"))
                    if needs_lease or case.get("fresh_lease"):
                        if lease_id:
                            released = await session.call_tool("session_control", {
                                "action": "release", "lease_id": lease_id})
                            assert not released.isError, str(released.content)
                            lease_id = None
                        state = await session.call_tool("session_control", {"action": "inspect"})
                        assert not state.isError, str(state.content)
                        if needs_lease:
                            claim = await session.call_tool("session_control", {
                                "action": "claim", "owner": "eval-fixture",
                                "expected_project": state.structuredContent["project_id"]})
                            assert not claim.isError, str(claim.content)
                            lease_id = claim.structuredContent["lease_id"]
                    if arguments.get("expected_project") == "$project":
                        state = await session.call_tool("session_control", {"action": "inspect"})
                        arguments["expected_project"] = state.structuredContent["project_id"]
                    if arguments.get("lease_id") == "$lease" or needs_lease:
                        arguments["lease_id"] = lease_id
                reply = await session.call_tool(case["tool"], arguments)
                if not reply.isError and case["tool"] == "session_control":
                    if arguments.get("action") == "claim":
                        lease_id = reply.structuredContent["lease_id"]
                    elif arguments.get("action") == "release":
                        lease_id = None
                error = "\n".join(getattr(item, "text", "") for item in reply.content)
                if case.get("error"):
                    assert reply.isError, "Expected an explicit MCP tool error"
                    assert case["error"].lower() in error.lower(), error
                    for path, digest in protected.items():
                        assert path.is_file(), f"Failed call deleted {path.name}"
                        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, (
                            f"Failed call changed {path.name}"
                        )
                else:
                    assert not reply.isError, error
                    data = reply.structuredContent
                    for path, value in case.get("equals", {}).items():
                        assert pointer(data, path) == value, f"Mismatch at {path}: {data}"
                    for path in case.get("required", []):
                        pointer(data, path)
                    if case.get("image"):
                        blocks = [item for item in reply.content if item.type == "image"]
                        assert len(blocks) == 1 and blocks[0].mimeType == "image/png"
                        assert base64.b64decode(blocks[0].data).startswith(b"\x89PNG\r\n\x1a\n")
                    for path in case.get("files", []):
                        target = workspace / path
                        assert target.is_file() and target.stat().st_size > 0, path
                for path in case.get("absent", []):
                    assert not (workspace / path).exists(), path
                results.append(
                    {"id": case["id"], "tool": case["tool"], "kind": case["kind"], "passed": True}
                )
            except (AssertionError, KeyError, TypeError, ValueError, OSError) as exc:
                results.append(
                    {
                        "id": case["id"],
                        "tool": case["tool"],
                        "kind": case["kind"],
                        "passed": False,
                        "reason": str(exc),
                    }
                )
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=MODES)
    parser.add_argument(
        "--blender", default="blender", help="Blender executable (native mode only)"
    )
    parser.add_argument(
        "--model-image",
        type=Path,
        help="Also run configured offline reconstruction on this original image",
    )
    args = parser.parse_args()
    if args.model_image and (args.mode != "native" or not args.model_image.is_file()):
        parser.error("--model-image requires native mode and an existing image")
    evaluator = ROOT / "node_modules/.bin/mcpeval"
    if not evaluator.exists():
        parser.error("Install the pinned evaluator with npm ci first")
    output_root = ROOT / ".tmp/evals"
    output_root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=f"{args.mode}-", dir=output_root))
    workspace = output / "workspace"
    workspace.mkdir()
    if args.model_image:
        shutil.copyfile(args.model_image, workspace / "input-model.png")
    (output / "outside").mkdir()
    (output / "outside/input.spp").write_bytes(b"outside-project")
    (output / "outside/input.obj").write_bytes(b"outside-mesh")
    (output / "outside/external.png").write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82')
    (workspace / "escape").symlink_to(output / "outside", target_is_directory=True)
    for path, content in {
        "existing.blend": b"preserve-project",
        "existing.glb": b"preserve-mesh",
        "existing.png": b"preserve-preview",
        "input.spp": b"simulated-project",
        "input.obj": b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
    }.items():
        (workspace / path).write_bytes(content)
    (workspace / "color.png").write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC'))
    (workspace / "existing").mkdir()
    env = dict(os.environ)
    env.update(
        {
            "MCPEVAL_HOME": str(output / "store"),
            "CAVI_BLENDER_CONNECTION": str(output / "connection.json"),
            "CAVI_BLENDER_WORKSPACE": str(workspace),
        }
    )
    with ExitStack() as stack:
        adapter = None
        if args.mode == "native":
            executable = shutil.which(args.blender)
            if not executable:
                parser.error("Blender unavailable; native evaluation was not run")
            log = stack.enter_context((output / "blender.log").open("w"))
            ready, child_ready = socket.socketpair()
            stack.enter_context(ready)
            stack.enter_context(child_ready)
            env["CAVI_EVAL_READY_FD"] = str(child_ready.fileno())
            process = subprocess.Popen(
                [
                    executable,
                    "--background",
                    "--factory-startup",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(ROOT / "evals/blender_session.py"),
                ],
                pass_fds=(child_ready.fileno(),),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=ROOT,
            )

            def stop():
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            stack.callback(stop)
            child_ready.close()
            readable, _, _ = select.select([ready], [], [], 45)
            if not readable or ready.recv(5) != b"ready":
                raise RuntimeError(
                    f"Blender bridge did not start; inspect {output / 'blender.log'}"
                )
        results = asyncio.run(
            exercise(args.mode, env, workspace, adapter, include_model=bool(args.model_image))
        )
        report = {
            "mode": args.mode,
            "application": APP,
            "cases": results,
            "native_evidence": args.mode == "native",
            "model_evaluation": "local image-to-3D" if args.model_image else "not run",
        }
        (output / "cases.json").write_text(json.dumps(report, indent=2) + "\n")
        manifest = "protocol" if args.mode == "protocol" else "core"
        command = [
            str(evaluator),
            "probe",
            "--server",
            f"{APP}-{args.mode}",
            "--manifest",
            str(ROOT / f"evals/{manifest}.manifest.json"),
            "--format",
            "json",
        ]
        if args.mode == "protocol":
            command.append("--gate-only")
        command.extend(["--", sys.executable, "-m", f"cavi_{APP}_mcp.server"])
        with (output / "mcpeval.json").open("w") as stream:
            evaluated = subprocess.run(command, env=env, cwd=ROOT, stdout=stream, check=False)
        failed = [case for case in results if not case["passed"]]
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "passed": len(results) - len(failed),
                    "failed": failed,
                    "mcpeval_exit": evaluated.returncode,
                    "artifacts": str(output),
                },
                indent=2,
            )
        )
        if failed or evaluated.returncode:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

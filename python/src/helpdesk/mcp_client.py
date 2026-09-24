"""A small MCP client for the helpdesk's server, as an MCP host runs one (chapter 12).

python -m helpdesk.mcp_client --as sam tools                       the server's tools
python -m helpdesk.mcp_client --as sam call get_ticket ticket_id=4  call one tool
python -m helpdesk.mcp_client --as sam resources                   its resources and templates
python -m helpdesk.mcp_client --as sam read helpdesk://tickets/4   read one resource
python -m helpdesk.mcp_client --as sam prompts                     its prompts
python -m helpdesk.mcp_client --as sam prompt draft_reply ticket_id=2

Add --wire to see every JSON-RPC message sent and received, and --legacy to open with the
initialize handshake of protocol 2025-11-25 instead of 2026-07-28's per-request metadata.

It does for one server what a host such as Claude Code does: starts python -m helpdesk.mcp_server
as a subprocess, with the member of staff in its environment (HELPDESK_STAFF), writes one JSON-RPC
message a line to its standard input, and reads one a line from its standard output. --as sets
that environment variable, as a host's configuration would; no message carries a person. A call's
arguments are NAME=VALUE pairs, read as JSON where they parse, as in python -m helpdesk.tools.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from typing import Any

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
CLIENT = {"name": "helpdesk-mcp-client", "version": "0.1.0"}
STAFF_VARIABLE = "HELPDESK_STAFF"  # the server's own name for it; the client never imports the server
TIMEOUT = 30  # seconds to wait for any one reply before giving up on the server


class ServerExited(RuntimeError):
    """The server stopped, or never started. The message holds what it wrote to standard error."""


class StdioClient:
    """One MCP server, run as a subprocess and spoken to over its standard streams."""

    def __init__(
        self,
        staff: str | None,
        *,
        legacy: bool = False,
        wire: Callable[[str, str], None] | None = None,
        command: Sequence[str] = (sys.executable, "-m", "helpdesk.mcp_server"),
    ) -> None:
        env = {k: v for k, v in os.environ.items() if k != STAFF_VARIABLE}
        if staff is not None:
            env[STAFF_VARIABLE] = staff
        self.legacy = legacy
        self.wire = wire
        self._next_id = 0
        self.opening: dict[str, Any] = {}  # the reply to server/discover or initialize
        self._stderr: list[str] = []
        self.notifications: list[dict[str, Any]] = []
        self.process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            encoding="utf-8",
        )
        # A thread for each stream, so a server that stops answering can't hang the client.
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._output = threading.Thread(
            target=self._read, args=(self.process.stdout, self._lines.put), daemon=True
        )
        self._output.start()
        self._errors = threading.Thread(
            target=self._read, args=(self.process.stderr, self._stderr.append), daemon=True
        )
        self._errors.start()

    @staticmethod
    def _read(stream: Any, keep: Callable[[Any], None]) -> None:
        for line in stream:
            keep(line.rstrip("\n"))
        keep(None)

    @property
    def stderr(self) -> str:
        return "\n".join(line for line in self._stderr if line is not None)

    def _send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message)
        if self.wire:
            self.wire("->", line)
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
        except OSError:
            raise ServerExited(self._exited()) from None

    def _exited(self) -> str:
        code = self.process.wait(timeout=TIMEOUT)
        self._errors.join(timeout=TIMEOUT)  # everything it wrote to standard error, not just the start
        return f"the server exited with code {code}. It said: {self.stderr or 'nothing'}"

    def request(
        self, method: str, params: dict[str, Any] | None = None, *, meta: bool = True
    ) -> dict[str, Any]:
        """Send one request and return the response: a dict with "result" or "error".

        In the 2026-07-28 era every request carries its protocol version and the client's
        capabilities in _meta, because the server keeps nothing from one request to the next.
        meta=False leaves them out, to show what a server does with a request that has none.
        """
        self._next_id += 1
        params = dict(params or {})
        if meta and not self.legacy:
            params["_meta"] = {
                "io.modelcontextprotocol/protocolVersion": MODERN,
                "io.modelcontextprotocol/clientInfo": CLIENT,
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params:
            message["params"] = params
        self._send(message)
        while True:
            try:
                line = self._lines.get(timeout=TIMEOUT)
            except queue.Empty:
                raise ServerExited(f"no reply to {method} within {TIMEOUT} seconds") from None
            if line is None:
                raise ServerExited(self._exited())
            if self.wire:
                self.wire("<-", line)
            reply = json.loads(line)
            if reply.get("id") == self._next_id:
                return reply
            self.notifications.append(reply)  # a notification, which this client only keeps

    def open(self) -> dict[str, Any]:
        """Start talking. 2026-07-28 has no handshake, so this asks server/discover what the server
        supports; the legacy era must initialize, then say it's initialized, before anything else."""
        if not self.legacy:
            self.opening = self.request("server/discover")
            return self.opening
        self.opening = self.request(
            "initialize", {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": CLIENT}
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self.opening

    def close(self) -> int:
        """The specification's shutdown for stdio: close the server's input and wait for it to exit."""
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            code = self.process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            code = self.process.wait()
        for thread, stream in ((self._output, self.process.stdout), (self._errors, self.process.stderr)):
            thread.join(timeout=TIMEOUT)
            if stream:
                stream.close()
        return code

    def __enter__(self) -> StdioClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def arguments_from(pairs: Sequence[str]) -> dict[str, Any]:
    arguments = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ValueError(f"Write each argument as NAME=VALUE, such as ticket_id=4; got {pair!r}.")
        try:
            arguments[key] = json.loads(value)
        except json.JSONDecodeError:
            arguments[key] = value
    return arguments


def show_error(error: dict[str, Any]) -> int:
    print(f"error {error['code']}: {error['message']}")
    return 1


def run(client: StdioClient, command: str, args: argparse.Namespace) -> int:
    opened = client.open()
    if "error" in opened:
        return show_error(opened["error"])
    result = opened["result"]
    info = result.get("serverInfo") or result.get("_meta", {}).get("io.modelcontextprotocol/serverInfo", {})
    era = LEGACY if client.legacy else MODERN
    print(f"{info.get('name')} {info.get('version')}, protocol {era}. {result.get('instructions', '')}\n")

    if command == "tools":
        reply = client.request("tools/list")
        if "error" in reply:
            return show_error(reply["error"])
        for tool in reply["result"]["tools"]:
            print(f"{tool['name']}({', '.join(tool['inputSchema'].get('properties', {}))})")
    elif command == "call":
        reply = client.request("tools/call", {"name": args.name, "arguments": arguments_from(args.arguments)})
        if "error" in reply:
            return show_error(reply["error"])
        label = "isError: true" if reply["result"].get("isError") else "result"
        print(label)
        print("\n".join(block["text"] for block in reply["result"]["content"]))
        return 1 if reply["result"].get("isError") else 0
    elif command == "resources":
        listed = client.request("resources/list")
        templates = client.request("resources/templates/list")
        for reply in (listed, templates):
            if "error" in reply:
                return show_error(reply["error"])
        for resource in listed["result"]["resources"]:
            print(f"{resource['uri']}  {resource.get('title', resource['name'])}")
        for template in templates["result"]["resourceTemplates"]:
            print(f"{template['uriTemplate']}  {template.get('title', template['name'])}")
    elif command == "read":
        reply = client.request("resources/read", {"uri": args.uri})
        if "error" in reply:
            return show_error(reply["error"])
        for contents in reply["result"]["contents"]:
            print(contents["text"])
        print(f"\ncacheScope: {reply['result'].get('cacheScope')}, ttlMs: {reply['result'].get('ttlMs')}")
    elif command == "prompts":
        reply = client.request("prompts/list")
        if "error" in reply:
            return show_error(reply["error"])
        for prompt in reply["result"]["prompts"]:
            names = ", ".join(a["name"] for a in prompt.get("arguments", []))
            print(f"{prompt['name']}({names})  {prompt.get('title', '')}")
    elif command == "prompt":
        given = {k: str(v) for k, v in arguments_from(args.arguments).items()}
        reply = client.request("prompts/get", {"name": args.name, "arguments": given})
        if "error" in reply:
            return show_error(reply["error"])
        for message in reply["result"]["messages"]:
            print(f"[{message['role']}]\n{message['content']['text']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.mcp_client")
    parser.add_argument("--as", dest="person", help=f"who the server acts for: sets {STAFF_VARIABLE}")
    parser.add_argument("--legacy", action="store_true", help=f"open with the {LEGACY} initialize handshake")
    parser.add_argument("--wire", action="store_true", help="print every message sent (->) and received (<-)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tools")
    sub.add_parser("resources")
    sub.add_parser("prompts")
    call = sub.add_parser("call")
    call.add_argument("name")
    call.add_argument("arguments", nargs="*", help="NAME=VALUE pairs, such as ticket_id=4")
    read = sub.add_parser("read")
    read.add_argument("uri")
    prompt = sub.add_parser("prompt")
    prompt.add_argument("name")
    prompt.add_argument("arguments", nargs="*", help="NAME=VALUE pairs, such as ticket_id=2")
    args = parser.parse_args()

    wire = (lambda direction, line: print(f"{direction} {line}")) if args.wire else None
    client = StdioClient(args.person, legacy=args.legacy, wire=wire)
    try:
        return run(client, args.command, args)
    except ServerExited as e:
        print(f"Stopped: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())

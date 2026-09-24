"""A small MCP client for the helpdesk's server, as an MCP host runs one (chapter 12).

python -m helpdesk.mcp_client --as sam tools                       the server's tools
python -m helpdesk.mcp_client --as sam call get_ticket ticket_id=4  call one tool
python -m helpdesk.mcp_client --as sam resources                   its resources and templates
python -m helpdesk.mcp_client --as sam read helpdesk://tickets/4   read one resource
python -m helpdesk.mcp_client --as sam prompts                     its prompts
python -m helpdesk.mcp_client --as sam prompt draft_reply ticket_id=2
python -m helpdesk.mcp_client --url http://127.0.0.1:8765/mcp --as sam call get_ticket ticket_id=2

Add --wire to see every JSON-RPC message sent and received, and --legacy to open with the
initialize handshake of protocol 2025-11-25 instead of 2026-07-28's per-request metadata.

It does for one server what a host such as Claude Code does: starts python -m helpdesk.mcp_server
as a subprocess, with the member of staff in its environment (HELPDESK_STAFF), writes one JSON-RPC
message a line to its standard input, and reads one a line from its standard output. --as sets
that environment variable, as a host's configuration would; no message carries a person. A call's
arguments are NAME=VALUE pairs, read as JSON where they parse, as in python -m helpdesk.tools.

With --url it speaks Streamable HTTP to a server that's already running (chapter 13), such as
python -m helpdesk.mcp_server --http, every message its own POST. --as then gets an access token
for that person from the lab's test issuer, for the server at --url (or --audience) and with the
scopes in --scope, and sends it with every request; without --as it sends no token. `metadata`
prints the server's Protected Resource Metadata. A refusal prints its HTTP status and challenge.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

from helpdesk.data.seed import STAFF
from mcp_governance import run_dir
from mcp_governance.tokens import LabIssuer

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
CLIENT = {"name": "helpdesk-mcp-client", "version": "0.1.0"}
STAFF_VARIABLE = "HELPDESK_STAFF"  # the server's own name for it; the client never imports the server
SCOPES = ("kb:read", "tickets:read")  # what --url asks for unless --scope says: all the server lists
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


class Refused(RuntimeError):
    """An answer over HTTP that isn't a JSON-RPC message: refused before the MCP server saw the request."""

    def __init__(self, status: int, reason: str, challenge: str | None, body: str) -> None:
        super().__init__(f"HTTP {status} {reason}")
        self.status = status
        self.reason = reason
        self.challenge = challenge
        self.body = body


# The methods whose target the 2026-07-28 transport copies into the Mcp-Name header, and where it is.
NAMED = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}


def header_value(value: str) -> str:
    """A value for Mcp-Name: as it is if it's plain printable ASCII, otherwise in the specification's
    Base64 form, =?base64?...?=."""
    plain = value.isascii() and value.isprintable() and value == value.strip() and not value.startswith("=?")
    return value if plain else f"=?base64?{base64.b64encode(value.encode()).decode()}?="


class HttpClient:
    """One MCP server over Streamable HTTP, revision 2026-07-28: every message its own POST, with the
    method and name copied into headers and the bearer token, if there is one, on every request."""

    legacy = False
    stderr = ""

    def __init__(
        self,
        url: str,
        token: str | None = None,
        *,
        wire: Callable[[str, str], None] | None = None,
        note: str = "",
    ) -> None:
        self.url = url
        self.token = token
        self.wire = wire
        self.note = note  # what the token is, for --wire, which never prints the token itself
        self._next_id = 0
        self.opening: dict[str, Any] = {}
        # No proxy: the lab's server is on this machine, and the token must go nowhere else.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _send(self, request: urllib.request.Request) -> tuple[int, str, dict[str, str], bytes]:
        try:
            with self._opener.open(request, timeout=TIMEOUT) as response:
                return response.status, response.reason, dict(response.headers), response.read()
        except urllib.error.HTTPError as e:
            return e.code, e.reason, dict(e.headers), e.read()
        except urllib.error.URLError as e:
            raise ServerExited(
                f"nothing answered at {request.full_url} ({e.reason}). Is the server running?"
            ) from None

    def request(
        self, method: str, params: dict[str, Any] | None = None, *, meta: bool = True
    ) -> dict[str, Any]:
        self._next_id += 1
        params = dict(params or {})
        if meta:
            params["_meta"] = {
                "io.modelcontextprotocol/protocolVersion": MODERN,
                "io.modelcontextprotocol/clientInfo": CLIENT,
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MODERN,
            "Mcp-Method": method,
        }
        if method in NAMED and isinstance(params.get(NAMED[method]), str):
            headers["Mcp-Name"] = header_value(params[NAMED[method]])
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = json.dumps(message)
        if self.wire:
            shown = {k: (f"Bearer ({self.note})" if k == "Authorization" else v) for k, v in headers.items()}
            self.wire(
                "->",
                f"POST {self.url} "
                + " ".join(f"{k}: {v}" for k, v in shown.items() if k.startswith(("Mcp", "Auth"))),
            )
            self.wire("->", body)
        request = urllib.request.Request(self.url, data=body.encode(), headers=headers, method="POST")
        status, reason, answer_headers, raw = self._send(request)
        challenge = next((v for k, v in answer_headers.items() if k.lower() == "www-authenticate"), None)
        text = raw.decode("utf-8", errors="replace")
        if self.wire:
            self.wire("<-", f"{status} {reason}" + (f" WWW-Authenticate: {challenge}" if challenge else ""))
            self.wire("<-", text)
        reply = parse_reply(text, answer_headers)
        if reply is None:
            raise Refused(status, reason, challenge, text)
        return reply

    def open(self) -> dict[str, Any]:
        self.opening = self.request("server/discover")
        return self.opening

    def metadata(self) -> dict[str, Any]:
        """The server's Protected Resource Metadata (RFC 9728), at the well-known path the MCP
        specification tries first: /.well-known/oauth-protected-resource, then the endpoint's path."""
        parts = urlsplit(self.url)
        where = f"{parts.scheme}://{parts.netloc}/.well-known/oauth-protected-resource{parts.path}"
        status, reason, _, raw = self._send(urllib.request.Request(where, method="GET"))
        if status != 200:
            raise Refused(status, reason, None, raw.decode("utf-8", errors="replace"))
        return json.loads(raw)

    def close(self) -> int:
        return 0

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def parse_reply(text: str, headers: dict[str, str]) -> dict[str, Any] | None:
    """A JSON-RPC reply from a JSON body or from the last event of a Server-Sent Events stream; None
    when the answer isn't one."""
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
    if content_type.startswith("text/event-stream"):
        events = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = events[-1] if events else ""
    try:
        reply = json.loads(text)
    except ValueError:
        return None
    return reply if isinstance(reply, dict) and reply.get("jsonrpc") == "2.0" else None


def subject_for(person: str) -> str:
    """The staff id the lab's issuer puts in a token's subject, for a first name or an id. A real
    issuer knows who signed in; the lab's reads the sample staff list."""
    for staff_id, name, _ in STAFF:
        if person.strip().lower() in (str(staff_id), name.split()[0].lower()):
            return str(staff_id)
    known = ", ".join(name.split()[0].lower() for _, name, _ in STAFF)
    raise ValueError(f"No member of staff called {person!r}. Choose one of: {known}.")


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


def run(client: StdioClient | HttpClient, command: str, args: argparse.Namespace) -> int:
    if command == "metadata":
        if not isinstance(client, HttpClient):
            raise ValueError("metadata is for a server over HTTP: give its address with --url.")
        print(json.dumps(client.metadata(), indent=2))
        return 0
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
    parser.add_argument(
        "--as",
        dest="person",
        help=f"who the server acts for: sets {STAFF_VARIABLE}, or with --url, the token's person",
    )
    parser.add_argument("--legacy", action="store_true", help=f"open with the {LEGACY} initialize handshake")
    parser.add_argument("--wire", action="store_true", help="print every message sent (->) and received (<-)")
    parser.add_argument("--url", help="a server over Streamable HTTP, such as http://127.0.0.1:8765/mcp")
    parser.add_argument(
        "--scope", default=" ".join(SCOPES), help=f'with --url, the token\'s scopes ("{" ".join(SCOPES)}")'
    )
    parser.add_argument("--audience", help="with --url, the server the token is issued for (default: --url)")
    parser.add_argument("--client", default=CLIENT["name"], help="with --url, the token's client_id")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("metadata")
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
    try:
        client = (
            http_client(args, wire) if args.url else StdioClient(args.person, legacy=args.legacy, wire=wire)
        )
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    try:
        return run(client, args.command, args)
    except Refused as e:
        print(f"Refused: HTTP {e.status} {e.reason}")
        print(f"WWW-Authenticate: {e.challenge}" if e.challenge else e.body)
        return 1
    except ServerExited as e:
        print(f"Stopped: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    finally:
        client.close()


def http_client(args: argparse.Namespace, wire: Callable[[str, str], None] | None) -> HttpClient:
    """A client for the server at --url, with a token for --as from the lab's test issuer, if --as is given.

    A real client asks the authorization server the server's metadata names, naming the server it wants
    the token for (the resource indicator, RFC 8707), and the person signs in. The lab has no
    authorization server, so it signs the token itself, for the person, the server and the scopes asked."""
    if args.legacy:
        raise ValueError("--legacy is for stdio. Over HTTP this client speaks 2026-07-28.")
    if args.person is None:
        return HttpClient(args.url, wire=wire)
    audience = args.audience or args.url
    scopes = args.scope.split()
    subject = subject_for(args.person)
    token = LabIssuer.at(run_dir()).issue(
        subject=subject, audience=audience, scopes=scopes, client_id=args.client
    )
    note = f'a token for {args.person} (subject {subject}), scope "{" ".join(scopes)}", for {audience}'
    return HttpClient(args.url, token, wire=wire, note=note)


if __name__ == "__main__":
    sys.exit(main())

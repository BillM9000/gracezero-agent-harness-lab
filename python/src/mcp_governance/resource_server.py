"""The front door of an MCP server over HTTP (chapter 13): tokens, scopes and an audit record.

ResourceServer is an ASGI application that sits in front of an MCP server speaking Streamable HTTP.
Before a request reaches the server, it:

1. requires a bearer token on every request to the MCP endpoint and verifies it (tokens.Verifier):
   issued by the trusted issuer, for this server alone, unexpired, for a person the server knows.
   Anything else gets 401 and a challenge that points at the server's metadata;
2. reads the request's JSON-RPC body, which is what the server will run, and requires the scopes
   that operation needs, answering 403 insufficient_scope with the scopes to ask for;
3. removes the Authorization header, so nothing behind it can pass the token on to another service;
4. hands the request to the MCP server built for the person the token names;

and it writes one audit record for every request, whatever the answer. It also serves the
Protected Resource Metadata (RFC 9728) that tells a client where tokens for this server come from.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

from mcp_governance.audit import UNKNOWN, AuditLog
from mcp_governance.tokens import TokenRefused, Verifier, canonical

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# What the server knows about a verified subject: how to name the person in the audit log, and the
# MCP server that acts for them. None when the subject isn't anyone the server knows.
PersonApp = tuple[str, ASGIApp]

MAX_BODY = 4 * 1024 * 1024  # bytes: the MCP SDK's own limit on a request body
METADATA = "/.well-known/oauth-protected-resource"


def header_safe(text: str) -> str:
    """RFC 6750 allows printable ASCII other than a quotation mark or backslash in an error_description."""
    return "".join(c if " " <= c <= "~" and c not in '"\\' else "'" if c == '"' else "?" for c in text)


class ResourceServer:
    """OAuth resource-server checks, per-operation scopes and an audit record, in front of an MCP server."""

    def __init__(
        self,
        *,
        resource: str,
        verifier: Verifier,
        authorization_servers: list[str],
        scopes_supported: list[str],
        required_scopes: Callable[[str, str | None], tuple[str, ...]],
        for_subject: Callable[[str], PersonApp | None],
        audit: AuditLog,
    ) -> None:
        self.resource = canonical(resource)
        parts = urlsplit(self.resource)
        self.path = parts.path or "/"
        # RFC 9728: the well-known path goes between the host and the resource's own path.
        self.metadata_path = METADATA + (parts.path if parts.path not in ("", "/") else "")
        self.metadata_url = f"{parts.scheme}://{parts.netloc}{self.metadata_path}"
        self.metadata = {
            "resource": self.resource,
            "authorization_servers": authorization_servers,
            "scopes_supported": scopes_supported,
            "bearer_methods_supported": ["header"],
        }
        self.verifier = verifier
        self.required_scopes = required_scopes
        self.for_subject = for_subject
        self.audit = audit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await lifespan(receive, send)
            return
        if scope["type"] != "http":
            return  # no websockets here
        if scope["path"] == self.metadata_path and scope["method"] == "GET":
            await respond(send, 200, self.metadata)
            return
        if scope["path"] != self.path:
            missing = {"error": "not_found", "error_description": f"The MCP endpoint is {self.path}."}
            await respond(send, 404, missing)
            return
        await self.endpoint(scope, receive, send)

    async def endpoint(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = await read_body(receive)
        if body is None:
            too_large = {"error": "invalid_request", "error_description": "The request is too large."}
            await respond(send, 413, too_large)
            return
        method, name, arguments = operation(body)
        needed = self.required_scopes(method, name) if method else ()
        record: dict[str, Any] = {
            "client": UNKNOWN,
            "subject": UNKNOWN,
            "person": UNKNOWN,
            "method": method or UNKNOWN,
            "name": name or UNKNOWN,
            "arguments": arguments,
            "token": UNKNOWN,
        }

        token = bearer(scope)
        if token is None:
            # No credentials at all: a challenge with no error code (RFC 6750), saying where to get a token.
            self.audit.record(**record, status=401, outcome="refused 401: no token")
            await self.refuse(send, 401, None, "This server needs a bearer token.", needed)
            return
        try:
            grant = self.verifier.verify(token)
        except TokenRefused as refused:
            self.audit.record(**record, status=401, outcome=f"refused 401: {refused.reason}")
            await self.refuse(send, 401, "invalid_token", f"The token was refused: {refused.reason}.", ())
            return
        record.update(client=grant.client_id, subject=grant.subject, token=grant.token_id)

        found = self.for_subject(grant.subject)
        if found is None:
            reason = f"its subject, {grant.subject}, isn't anyone this server acts for"
            self.audit.record(**record, status=401, outcome=f"refused 401: {reason}")
            await self.refuse(send, 401, "invalid_token", f"The token was refused: {reason}.", ())
            return
        person, app = found
        record["person"] = person

        # Least privilege: the token must carry every scope this operation needs. The person's own
        # permissions still apply inside the server; a scope can only narrow them, never widen them.
        missing = [s for s in needed if s not in grant.scopes]
        if missing:
            self.audit.record(**record, status=403, outcome=f"refused 403: needs {' '.join(missing)}")
            description = (
                f"{method} {name} needs the scope {' '.join(needed)}, which this token doesn't carry."
            )
            await self.refuse(send, 403, "insufficient_scope", description, needed)
            return

        status, outcome = await self.forward(app, without_authorization(scope), replay(body, receive), send)
        self.audit.record(**record, status=status, outcome=outcome)

    async def forward(self, app: ASGIApp, scope: Scope, receive: Receive, send: Send) -> tuple[int, str]:
        """Serve the request with the person's MCP server, and say what its answer was."""
        answer: dict[str, Any] = {"status": 500, "body": b""}

        async def watching(message: Message) -> None:
            if message["type"] == "http.response.start":
                answer["status"] = message["status"]
            elif message["type"] == "http.response.body":
                answer["body"] += message.get("body", b"")
            await send(message)

        await app(scope, receive, watching)
        return answer["status"], outcome(answer["status"], answer["body"])

    async def refuse(
        self, send: Send, status: int, error: str | None, description: str, scopes: tuple[str, ...]
    ) -> None:
        """A refusal with its WWW-Authenticate challenge: the error, the scopes to ask for, and where the
        metadata is, as the MCP specification's authorization page shows them."""
        parts = [f'error="{error}"'] if error else []
        if scopes:
            parts.append(f'scope="{" ".join(scopes)}"')
        parts.append(f'resource_metadata="{self.metadata_url}"')
        if error:
            parts.append(f'error_description="{header_safe(description)}"')
        body = {"error": error or "unauthorized", "error_description": description}
        challenge = ("Bearer " + ", ".join(parts)).encode("ascii")
        await respond(send, status, body, ((b"www-authenticate", challenge),))


async def lifespan(receive: Receive, send: Send) -> None:
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def respond(
    send: Send, status: int, body: dict[str, Any], headers: tuple[tuple[bytes, bytes], ...] = ()
) -> None:
    data = json.dumps(body).encode("utf-8")
    start = [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode()), *headers]
    await send({"type": "http.response.start", "status": status, "headers": start})
    await send({"type": "http.response.body", "body": data})


async def read_body(receive: Receive) -> bytes | None:
    """The whole request body, or None if it's larger than MAX_BODY."""
    body = b""
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return body
        body += message.get("body", b"")
        if len(body) > MAX_BODY:
            return None
        if not message.get("more_body"):
            return body


def replay(body: bytes, receive: Receive) -> Receive:
    """A receive that hands the server the body already read, then carries on with the connection."""
    sent = False

    async def again() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return again


def bearer(scope: Scope) -> str | None:
    """The token from an Authorization: Bearer header, the one place the specification allows it."""
    for key, value in scope["headers"]:
        if key.lower() == b"authorization":
            kind, _, token = value.decode("latin-1").partition(" ")
            if kind.lower() != "bearer" or not token.strip():
                return None
            return token.strip()
    return None


def without_authorization(scope: Scope) -> Scope:
    """The request as the MCP server sees it: without the token. The server was built for the person
    the token names, so it needs nothing more from it, and what it never holds it can't pass on."""
    return {**scope, "headers": [(k, v) for k, v in scope["headers"] if k.lower() != b"authorization"]}


def operation(body: bytes) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """The JSON-RPC method, the tool, prompt or resource it names, and its arguments, read from the body
    itself: what the server will run. (A 2026-07-28 client also copies the method and name into the
    Mcp-Method and Mcp-Name headers, and the MCP SDK refuses a request whose headers and body differ.)"""
    try:
        message = json.loads(body)
    except ValueError:
        return None, None, None
    if not isinstance(message, dict) or not isinstance(message.get("method"), str):
        return None, None, None
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    target = params.get("uri") if message["method"] == "resources/read" else params.get("name")
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else None
    return message["method"], target if isinstance(target, str) else None, arguments


def outcome(status: int, body: bytes) -> str:
    """What the MCP server's answer was, for the audit log."""
    try:
        reply = json.loads(body)
    except ValueError:
        return "ok" if status < 400 else f"HTTP {status}"
    if not isinstance(reply, dict):
        return "ok" if status < 400 else f"HTTP {status}"
    if isinstance(reply.get("error"), dict):
        return f"error {reply['error'].get('code')}"
    if isinstance(reply.get("result"), dict) and reply["result"].get("isError"):
        return "tool error"
    return "ok" if status < 400 else f"HTTP {status}"

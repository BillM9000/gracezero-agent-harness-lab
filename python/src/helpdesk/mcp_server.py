"""Composition root for the helpdesk's MCP server (chapters 12 and 13).

HELPDESK_STAFF=sam python -m helpdesk.mcp_server    serve MCP on stdio, acting for Sam
python -m helpdesk.mcp_server --http                serve Streamable HTTP on 127.0.0.1:8765,
                                                    for the person each request's token names

On stdio, an MCP host starts this as a subprocess and speaks JSON-RPC to it, one message a line,
over its standard input and output. python -m helpdesk.mcp_client plays the host.

Who the server acts for comes from its environment, which whoever configures the host sets, and
never from a message: the MCP specification says a server on stdio takes its credentials from the
environment. With no HELPDESK_STAFF, or a name that isn't on the staff list, it refuses to start;
it never picks a person itself. In the lab the variable names the person; it doesn't prove who.

Over HTTP (chapter 13), one server serves everyone, as an OAuth resource server: every request
carries an access token, which mcp_governance.ResourceServer verifies (issued by the lab's test
issuer, for this server alone, unexpired) before the request is served by the same server as on
stdio, built for the person the token names. Each operation needs a scope (required_scopes), every
request is written to the audit log, and the server refuses to start if its tools or scopes differ
from its entry in the catalog of approved servers (catalog/servers.toml).

It offers three kinds of thing, and each is another way in to the same data:
- tools: the triage assistant's three (helpdesk/assistant/tools.py), run through the same toolbox,
  so the same argument checks, errors and result sizes apply;
- resources: each help article, and each ticket as a record (helpdesk://tickets/{ticket_id});
- a prompt, draft_reply, with the ticket in it.
Everything that shows a ticket applies helpdesk/services/access.py for the same person.

It speaks both protocol eras through the MCP Python SDK: 2026-07-28, where every request carries its
own version and capabilities, and the initialize handshake of 2025-11-25 and earlier. Each run
serves a fresh in-memory copy of the sample data, so nothing is saved.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import anyio
import uvicorn
from mcp import types
from mcp.server import CacheHint, Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from mcp.types.jsonrpc import INVALID_PARAMS
from mcp.types.version import HANDSHAKE_PROTOCOL_VERSIONS

from helpdesk.assistant.tools import Toolbox, triage_tools
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed
from helpdesk.model.types import ToolCall
from helpdesk.services import access, kb, tickets
from helpdesk.services.access import Person
from helpdesk.services.errors import Invalid, ServiceError
from mcp_governance import SERVERS, load, run_dir
from mcp_governance.audit import AuditLog
from mcp_governance.catalog import entry, offered_differs
from mcp_governance.resource_server import ASGIApp, PersonApp, Receive, ResourceServer, Scope, Send
from mcp_governance.tokens import ISSUER, Verifier, public_key_at

STAFF_VARIABLE = "HELPDESK_STAFF"
TICKETS = "helpdesk://tickets/"
ARTICLES = "helpdesk://kb/"

# The lists are the same for everyone and change only with the server's code, so any cache may keep
# them for an hour. A help article is the same for everyone too. A ticket is not: see read_resource.
PUBLIC_FOR_AN_HOUR = CacheHint(ttl_ms=3_600_000, scope="public")
CACHE_HINTS = {
    "tools/list": PUBLIC_FOR_AN_HOUR,
    "prompts/list": PUBLIC_FOR_AN_HOUR,
    "resources/list": PUBLIC_FOR_AN_HOUR,
    "resources/templates/list": PUBLIC_FOR_AN_HOUR,
}

DRAFT_REPLY = types.Prompt(
    name="draft_reply",
    title="Draft a reply to a ticket",
    description="The ticket in full, with instructions to draft a reply for you to review before anything "
    "is sent. It holds only a ticket you may see.",
    arguments=[
        types.PromptArgument(name="ticket_id", description="The ticket's number, such as 2.", required=True)
    ],
)

# Over HTTP (chapter 13): the scope each operation needs, beyond a token issued for this server.
# Discovery and the lists need nothing more. A ticket needs tickets:read through every way in: the
# tools, the ticket resource and the prompt. A test requires every tool offered to have a scope here.
TOOL_SCOPES = {"get_ticket": "tickets:read", "find_tickets": "tickets:read", "search_kb": "kb:read"}
PROMPT_SCOPES = {DRAFT_REPLY.name: "tickets:read"}
RESOURCE_SCOPES = {TICKETS: "tickets:read", ARTICLES: "kb:read"}
SCOPES_SUPPORTED = sorted({*TOOL_SCOPES.values(), *PROMPT_SCOPES.values(), *RESOURCE_SCOPES.values()})
HTTP_HOST = "127.0.0.1"  # the specification asks a server running locally to listen on localhost only
HTTP_PORT = 8765
CATALOG_NAME = "helpdesk"  # this server's entry in the catalog of approved servers
# The code the revisions with the initialize handshake (2024-11-05 to 2025-11-25) give a resource that
# doesn't exist. 2026-07-28 uses -32602 (Invalid Params) instead, and the SDK names only that one.
RESOURCE_NOT_FOUND = -32002


def required_scopes(method: str, name: str | None) -> tuple[str, ...]:
    """The scopes one request needs. A tool, prompt or resource this server doesn't have needs none:
    the server refuses it as unknown, the same for every token."""
    if method == "tools/call" and name in TOOL_SCOPES:
        return (TOOL_SCOPES[name],)
    if method == "prompts/get" and name in PROMPT_SCOPES:
        return (PROMPT_SCOPES[name],)
    if method == "resources/read" and name:
        for prefix, scope in RESOURCE_SCOPES.items():
            if name.startswith(prefix):
                return (scope,)
    return ()


def not_found(ctx: ServerRequestContext[Any], message: str, uri: str) -> MCPError:
    # The specification's code for a resource that doesn't exist, in the revision the client speaks,
    # which the SDK keeps from the handshake or from the request's own metadata. A ticket the person
    # can't see gets it too, with the same words as a missing one (access.cannot_see).
    code = RESOURCE_NOT_FOUND if ctx.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS else INVALID_PARAMS
    return MCPError(code, message, {"uri": uri})


def build_server(conn: sqlite3.Connection, person: Person) -> Server[Any]:
    """The helpdesk's MCP server, acting for one member of staff. Nothing a client sends changes who."""
    toolbox: Toolbox = triage_tools(conn, person)
    names = [spec.name for spec in toolbox.specs]

    async def list_tools(ctx: ServerRequestContext[Any], params: Any) -> types.ListToolsResult:
        # The schemas go out whole, minimum and all: MCP's input schemas are JSON Schema 2020-12,
        # without the subset a model provider's strict mode accepts (chapter 11). The toolbox checks
        # every call against them anyway.
        read_only = types.ToolAnnotations(read_only_hint=True, open_world_hint=False)
        tools = [
            types.Tool(
                name=s.name, description=s.description, input_schema=s.input_schema, annotations=read_only
            )
            for s in toolbox.specs
        ]
        return types.ListToolsResult(tools=tools)

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        if params.name not in names:
            # A tool that doesn't exist is a protocol error, not a result, by the specification.
            raise MCPError(INVALID_PARAMS, f"Unknown tool: {params.name}. The tools are {', '.join(names)}.")
        result = toolbox.run(ToolCall("mcp", params.name, dict(params.arguments or {})))
        # Bad arguments, a ticket the person can't see and a fault in the tool all come back as a
        # result marked isError, with chapter 11's message, so the model can read it and act on it.
        return types.CallToolResult(
            content=[types.TextContent(text=result.content)], is_error=result.is_error
        )

    async def list_resources(ctx: ServerRequestContext[Any], params: Any) -> types.ListResourcesResult:
        articles = [
            types.Resource(
                uri=f"{ARTICLES}{a['id']}", name=f"kb-{a['id']}", title=a["title"], mime_type="text/markdown"
            )
            for a in kb.articles(conn)
        ]
        return types.ListResourcesResult(resources=articles)

    async def list_templates(
        ctx: ServerRequestContext[Any], params: Any
    ) -> types.ListResourceTemplatesResult:
        ticket = types.ResourceTemplate(
            uri_template=TICKETS + "{ticket_id}",
            name="ticket",
            title="A ticket, as its record",
            description="One ticket and its replies, as JSON. Only tickets you may see can be read.",
            mime_type="application/json",
        )
        return types.ListResourceTemplatesResult(resource_templates=[ticket])

    async def read_resource(
        ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        uri = str(params.uri)
        number = uri.removeprefix(TICKETS) if uri.startswith(TICKETS) else uri.removeprefix(ARTICLES)
        if not uri.startswith((TICKETS, ARTICLES)) or not number.isdigit():
            raise not_found(
                ctx, f"No resource at {uri}. Tickets are {TICKETS}N and help articles {ARTICLES}N.", uri
            )
        if uri.startswith(TICKETS):
            try:
                ticket = tickets.visible_ticket(conn, person, int(number))
            except ServiceError as e:
                raise not_found(ctx, str(e), uri) from None
            record = types.TextResourceContents(
                uri=uri, mime_type="application/json", text=json.dumps(ticket, indent=2)
            )
            # What this person may see: never shared with anyone else's cache, and stale as soon as it
            # arrives (a time to live of 0), because tickets change as people work on them.
            return types.ReadResourceResult(contents=[record], ttl_ms=0, cache_scope="private")
        article = next((a for a in kb.articles(conn) if a["id"] == int(number)), None)
        if article is None:
            raise not_found(ctx, f"There is no help article {number}. resources/list names them all.", uri)
        text = f"# {article['title']}\n\n{article['body']}"
        page = types.TextResourceContents(uri=uri, mime_type="text/markdown", text=text)
        return types.ReadResourceResult(contents=[page], ttl_ms=3_600_000, cache_scope="public")

    async def list_prompts(ctx: ServerRequestContext[Any], params: Any) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[DRAFT_REPLY])

    async def get_prompt(
        ctx: ServerRequestContext[Any], params: types.GetPromptRequestParams
    ) -> types.GetPromptResult:
        if params.name != DRAFT_REPLY.name:
            raise MCPError(
                INVALID_PARAMS, f"Unknown prompt: {params.name}. The prompt is {DRAFT_REPLY.name}."
            )
        given = (params.arguments or {}).get("ticket_id", "")
        # Prompt arguments arrive as text; the ticket is read through the same tool, for the same person.
        ticket_id: Any = int(given) if given.strip().isdigit() else given
        ticket = toolbox.run(ToolCall("prompt", "get_ticket", {"ticket_id": ticket_id}))
        if ticket.is_error:
            raise MCPError(INVALID_PARAMS, ticket.content)
        task = (
            f"Draft a reply to this ticket for {person.name} to review before anything is sent. Search "
            "the help articles with search_kb first, end each sentence that states a fact from them with "
            "the passage's id, such as [1#2], and say so if they don't cover the problem."
        )
        message = types.PromptMessage(
            role="user", content=types.TextContent(text=f"{task}\n\n{ticket.content}")
        )
        return types.GetPromptResult(description=f"Draft a reply to ticket {ticket_id}", messages=[message])

    return Server(
        "helpdesk",
        version=version("helpdesk"),
        instructions=(
            f"A small helpdesk's tickets and help articles, acting for {person.label}: every tool, "
            "resource and prompt shows only what that person may see, and nothing here changes a ticket."
        ),
        cache_hints=CACHE_HINTS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_list_resource_templates=list_templates,
        on_read_resource=read_resource,
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
    )


async def serve(server: Server[Any]) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def mcp_app_for(conn: sqlite3.Connection, person: Person) -> ASGIApp:
    """The server build_server makes for one person, answering one request over Streamable HTTP.
    Revision 2026-07-28 keeps nothing from one request to the next, so neither does this: every
    request gets a server built for the person its token names, and the server is gone after it."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        http = build_server(conn, person).streamable_http_app(
            stateless_http=True, json_response=True, host=HTTP_HOST
        )
        async with http.router.lifespan_context(http):
            await http(scope, receive, send)

    return app


def build_http_app(
    conn: sqlite3.Connection, *, resource: str, verifier: Verifier, audit: AuditLog
) -> ResourceServer:
    """The helpdesk over HTTP: the resource server's checks, then the person's own MCP server."""

    def for_subject(subject: str) -> PersonApp | None:
        # The token's subject is a staff id. The person is looked up on every request, never cached,
        # so someone removed from the staff list is refused from their next request on.
        person = next((p for p in access.staff(conn) if str(p.id) == subject), None)
        return None if person is None else (person.label, mcp_app_for(conn, person))

    return ResourceServer(
        resource=resource,
        verifier=verifier,
        authorization_servers=[ISSUER],
        scopes_supported=SCOPES_SUPPORTED,
        required_scopes=required_scopes,
        for_subject=for_subject,
        audit=audit,
    )


def catalog_problems(conn: sqlite3.Connection, server: dict[str, Any] | None) -> list[str]:
    """How this server differs from the one the catalog approved. Empty when they match."""
    if server is None:
        return [f"the catalog has no entry for {CATALOG_NAME}, so it was never approved"]
    # Which tools exist doesn't depend on who they act for.
    offered = [spec.name for spec in triage_tools(conn, Person(0, "Catalog Check", "none")).specs]
    problems = offered_differs(server, tools=offered, scopes=SCOPES_SUPPORTED)
    problems += [
        f"its tool {name} needs no scope: give it one in TOOL_SCOPES"
        for name in offered
        if name not in TOOL_SCOPES
    ]
    return problems


def shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def serve_http(port: int, catalog: Path) -> int:
    if os.environ.get(STAFF_VARIABLE, "").strip():
        print(
            f"Refused: {STAFF_VARIABLE} is set, but over HTTP the person comes from each request's token, "
            f"never from the server's environment. Unset it: it's for the stdio server.",
            file=sys.stderr,
        )
        return 2
    conn = connect(":memory:")
    try:
        init_schema(conn)
        seed(conn)
        # Check what will run against what was approved, before serving anything (chapter 18's rule).
        problems = catalog_problems(conn, entry(load(catalog), CATALOG_NAME))
        if problems:
            for problem in problems:
                print(f"Refused: {problem}.", file=sys.stderr)
            print(f"Nothing was served: this isn't the server {shown(catalog)} approved.", file=sys.stderr)
            return 2
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind((HTTP_HOST, port))
        except OSError as e:
            listener.close()
            print(f"Refused: can't listen on {HTTP_HOST}:{port} ({e.strerror}). Try --port.", file=sys.stderr)
            return 2
        resource = f"http://{HTTP_HOST}:{listener.getsockname()[1]}/mcp"
        folder = run_dir()
        # The server reads only the issuer's public key: it checks tokens, and can never make one.
        verifier = Verifier(public_key_at(folder), issuer=ISSUER, audience=resource)
        audit = AuditLog(folder / "audit.jsonl")
        app = build_http_app(conn, resource=resource, verifier=verifier, audit=audit)
        print(
            f"helpdesk MCP server: {resource}, over Streamable HTTP, for the person each request's token "
            f"names. It accepts tokens from {ISSUER} issued for that address; audit log {shown(audit.path)}.",
            file=sys.stderr,
            flush=True,
        )
        try:
            uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])
        finally:
            audit.close()
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helpdesk.mcp_server")
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP, for each request's token")
    parser.add_argument(
        "--port", type=int, default=HTTP_PORT, help=f"with --http, the port (default {HTTP_PORT})"
    )
    parser.add_argument(
        "--catalog", type=Path, default=SERVERS, help="with --http, the catalog to check against"
    )
    args = parser.parse_args(argv)
    return serve_http(args.port, args.catalog) if args.http else serve_stdio()


def serve_stdio() -> int:
    who = os.environ.get(STAFF_VARIABLE, "").strip()
    if not who:
        print(
            f"Refused: set {STAFF_VARIABLE} to the member of staff this server acts for, such as "
            f"{STAFF_VARIABLE}=sam. It never chooses one itself.",
            file=sys.stderr,
        )
        return 2
    conn = connect(":memory:")
    try:
        init_schema(conn)
        seed(conn)
        try:
            person = access.find_person(conn, who)
        except Invalid as e:
            print(f"Refused: {e}", file=sys.stderr)
            return 2
        # Standard output carries MCP messages and nothing else, so anything for a person goes to
        # standard error, which hosts show or log.
        print(f"helpdesk MCP server: acting for {person.label}, on stdio.", file=sys.stderr)
        anyio.run(serve, build_server(conn, person))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

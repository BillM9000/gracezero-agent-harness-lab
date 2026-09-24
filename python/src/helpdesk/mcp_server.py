"""Composition root for the helpdesk's MCP server (chapter 12).

HELPDESK_STAFF=sam python -m helpdesk.mcp_server    serve MCP on stdio, acting for Sam

An MCP host starts this as a subprocess and speaks JSON-RPC to it, one message a line, over its
standard input and output. python -m helpdesk.mcp_client plays the host.

Who the server acts for comes from its environment, which whoever configures the host sets, and
never from a message: the MCP specification says a server on stdio takes its credentials from the
environment. With no HELPDESK_STAFF, or a name that isn't on the staff list, it refuses to start;
it never picks a person itself. In the lab the variable names the person. A real deployment would
put a credential there that proves who it is, or serve over HTTP with the specification's OAuth
authorization, which chapter 13 covers.

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

import json
import os
import sqlite3
import sys
from importlib.metadata import version
from typing import Any

import anyio
from mcp import types
from mcp.server import CacheHint, Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from mcp.types.jsonrpc import INVALID_PARAMS

from helpdesk.assistant.tools import Toolbox, triage_tools
from helpdesk.data.db import connect, init_schema
from helpdesk.data.seed import seed
from helpdesk.model.types import ToolCall
from helpdesk.services import access, kb, tickets
from helpdesk.services.access import Person
from helpdesk.services.errors import Invalid, ServiceError

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


def not_found(message: str, uri: str) -> MCPError:
    # The specification's code for a resource that doesn't exist. A ticket the person can't see
    # gets it too, with the same words as a missing one (access.cannot_see).
    return MCPError(INVALID_PARAMS, message, {"uri": uri})


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
                f"No resource at {uri}. Tickets are {TICKETS}N and help articles {ARTICLES}N.", uri
            )
        if uri.startswith(TICKETS):
            try:
                ticket = tickets.visible_ticket(conn, person, int(number))
            except ServiceError as e:
                raise not_found(str(e), uri) from None
            record = types.TextResourceContents(
                uri=uri, mime_type="application/json", text=json.dumps(ticket, indent=2)
            )
            # What this person may see, fetched now: never shared with anyone else's cache, never
            # kept, because tickets change as people work on them.
            return types.ReadResourceResult(contents=[record], ttl_ms=0, cache_scope="private")
        article = next((a for a in kb.articles(conn) if a["id"] == int(number)), None)
        if article is None:
            raise not_found(f"There is no help article {number}. resources/list names them all.", uri)
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


def main() -> int:
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

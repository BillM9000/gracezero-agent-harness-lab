"""The helpdesk's MCP server, driven the way a host drives it (chapter 12).

Each test starts python -m helpdesk.mcp_server as a subprocess, with the member of staff in its
environment, and speaks JSON-RPC to it over its standard input and output, one message a line.
The protocol is stateless in its 2026-07-28 era, so one server process serves many tests.
"""

from __future__ import annotations

import json
import subprocess
import sys

import anyio
import pytest

from helpdesk.assistant.tools import triage_tools
from helpdesk.mcp_client import LEGACY, MODERN, ServerExited, StdioClient
from helpdesk.services import access

HIDDEN = "App crashes on login"  # ticket 4's subject; it's assigned to Dana, the lead


def opened(staff: str, **options: object) -> StdioClient:
    client = StdioClient(staff, **options)  # type: ignore[arg-type]
    assert "result" in client.open(), client.stderr
    return client


@pytest.fixture(scope="module")
def sam():
    with opened("sam") as client:
        yield client


@pytest.fixture(scope="module")
def dana():
    with opened("dana") as client:
        yield client


def call(client: StdioClient, name: str, **arguments: object) -> dict:
    return client.request("tools/call", {"name": name, "arguments": arguments})


def text(reply: dict) -> str:
    return "\n".join(block["text"] for block in reply["result"]["content"])


def read(client: StdioClient, uri: str) -> dict:
    return client.request("resources/read", {"uri": uri})


def prompt(client: StdioClient, ticket_id: str) -> dict:
    return client.request("prompts/get", {"name": "draft_reply", "arguments": {"ticket_id": ticket_id}})


# Opening: two eras.


def test_discovery_names_the_version_the_capabilities_and_who_it_acts_for(sam):
    result = sam.opening["result"]
    assert result["supportedVersions"] == [MODERN]
    assert {"tools", "resources", "prompts"} <= set(result["capabilities"])
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "helpdesk"
    assert "acting for Sam Rivera (support)" in result["instructions"]


def test_the_legacy_handshake_negotiates_its_version_and_serves_the_same_tools_for_the_same_person():
    with opened("sam", legacy=True) as client:
        result = client.opening["result"]
        assert result["protocolVersion"] == LEGACY
        assert result["serverInfo"]["name"] == "helpdesk"
        assert {"tools", "resources", "prompts"} <= set(result["capabilities"])
        assert client.request("tools/list")["result"]["tools"][0]["name"] == "get_ticket"
        refused = call(client, "get_ticket", ticket_id=4)
    assert refused["result"]["isError"] is True
    assert "Sam Rivera can't see ticket 4" in text(refused)


def test_every_request_carries_its_own_version_and_capabilities(sam):
    # Nothing is remembered from the discover call: a request without _meta is malformed.
    bare = sam.request("tools/list", meta=False)
    assert bare["error"]["code"] == -32602
    unknown = {
        "io.modelcontextprotocol/protocolVersion": "1900-01-01",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    old = sam.request("tools/list", {"_meta": unknown}, meta=False)
    assert old["error"]["code"] == -32022
    assert old["error"]["data"] == {"supported": [MODERN], "requested": "1900-01-01"}


# Tools.


def test_the_tools_are_the_assistants_own_with_their_whole_schemas(sam, conn):
    listed = sam.request("tools/list")["result"]
    specs = triage_tools(conn, access.find_person(conn, "sam")).specs
    assert [t["name"] for t in listed["tools"]] == [s.name for s in specs]
    for tool, spec in zip(listed["tools"], specs, strict=True):
        assert tool["inputSchema"] == spec.input_schema  # minimum and additionalProperties included
        assert tool["description"] == spec.description
        assert tool["annotations"] == {"readOnlyHint": True, "openWorldHint": False}
    assert listed["cacheScope"] == "public"


def test_the_tools_act_for_the_person_in_the_servers_environment(sam, dana):
    refused = call(sam, "get_ticket", ticket_id=4)
    assert refused["result"]["isError"] is True
    assert text(refused).startswith("Sam Rivera can't see ticket 4:")
    shown = call(dana, "get_ticket", ticket_id=4)
    assert shown["result"]["isError"] is False
    assert text(shown).startswith(f'Ticket 4 [closed, normal priority]: "{HIDDEN}"')
    assert "Tickets Sam Rivera can see (any status, any assignee): 9," in text(
        call(sam, "find_tickets", status="any")
    )
    assert "Tickets Dana Whitfield can see (any status, any assignee): 12," in text(
        call(dana, "find_tickets", status="any")
    )


def test_no_argument_can_choose_whose_permissions_a_tool_uses(sam):
    borrowed = call(sam, "get_ticket", ticket_id=4, staff_id=2)
    assert borrowed["result"]["isError"] is True
    assert "staff_id isn't one of its arguments (it takes ticket_id)" in text(borrowed)
    assert HIDDEN not in text(borrowed)


def test_bad_arguments_come_back_as_a_result_the_model_can_act_on(sam):
    bad = call(sam, "find_tickets", status="solved", page=0)
    assert bad["result"]["isError"] is True
    assert text(bad) == (
        'find_tickets wasn\'t run, because of 2 problems: status must be "open", "pending", "closed" or '
        '"any", not "solved"; page must be 1 or more, not 0. Call it again with both fixed.'
    )


def test_an_unknown_tool_is_a_protocol_error_that_names_the_tools(sam):
    reply = call(sam, "close_ticket", ticket_id=1)
    assert reply["error"]["code"] == -32602
    assert (
        reply["error"]["message"]
        == "Unknown tool: close_ticket. The tools are get_ticket, find_tickets, search_kb."
    )


# Resources.


def test_the_resources_are_the_help_articles_and_a_ticket_template(sam):
    listed = sam.request("resources/list")["result"]
    assert len(listed["resources"]) == 14
    assert listed["resources"][0] == {
        "uri": "helpdesk://kb/1",
        "name": "kb-1",
        "title": "Resetting your password",
        "mimeType": "text/markdown",
    }
    templates = sam.request("resources/templates/list")["result"]["resourceTemplates"]
    assert [t["uriTemplate"] for t in templates] == ["helpdesk://tickets/{ticket_id}"]


def test_a_help_article_reads_the_same_for_everyone_and_any_cache_may_keep_it(sam):
    result = read(sam, "helpdesk://kb/1")["result"]
    assert result["contents"][0]["text"].startswith(
        "# Resetting your password\n\n## Send yourself a reset link"
    )
    assert result["cacheScope"] == "public"
    assert read(sam, "helpdesk://kb/99")["error"]["code"] == -32602


def test_a_ticket_resource_applies_the_same_rule_as_the_tools(sam, dana):
    hidden = read(sam, "helpdesk://tickets/4")["error"]
    missing = read(sam, "helpdesk://tickets/999")["error"]
    assert hidden["code"] == missing["code"] == -32602
    # The same words for a ticket Sam can't see and one that doesn't exist, so the error leaks nothing.
    assert hidden["message"].replace("ticket 4", "ticket N") == missing["message"].replace(
        "ticket 999", "ticket N"
    )
    assert hidden["data"] == {"uri": "helpdesk://tickets/4"}
    record = json.loads(read(dana, "helpdesk://tickets/4")["result"]["contents"][0]["text"])
    assert record["subject"] == HIDDEN
    assert json.loads(read(sam, "helpdesk://tickets/2")["result"]["contents"][0]["text"])["assignee_id"] == 1


def test_a_ticket_record_is_never_kept_for_anyone_else(dana):
    # A shared cache that kept Dana's copy could hand it to Sam; "private" forbids that.
    result = read(dana, "helpdesk://tickets/4")["result"]
    assert (result["cacheScope"], result["ttlMs"]) == ("private", 0)


def test_a_uri_that_names_nothing_is_refused(sam):
    for uri in ("helpdesk://tickets/four", "helpdesk://customers/1", "file:///etc/passwd"):
        assert read(sam, uri)["error"]["code"] == -32602


def test_a_missing_resource_gets_the_code_of_the_revision_the_client_speaks(sam):
    # 2026-07-28 answers a resource that doesn't exist with -32602 (Invalid Params); 2025-11-25 and
    # the revisions before it answered -32002, so a host that opened with the handshake looks for that.
    uris = ("helpdesk://tickets/999", "helpdesk://tickets/4", "helpdesk://kb/99", "helpdesk://customers/1")
    modern = [read(sam, uri)["error"] for uri in uris]
    with opened("sam", legacy=True) as client:
        legacy = [read(client, uri)["error"] for uri in uris]
    assert [e["code"] for e in modern] == [-32602] * len(uris)
    assert [e["code"] for e in legacy] == [-32002] * len(uris)
    # Only the code changes: the same words and the same data in either revision.
    assert [(e["message"], e["data"]) for e in legacy] == [(e["message"], e["data"]) for e in modern]


# Prompts.


def test_the_prompt_holds_only_a_ticket_the_person_may_see(sam, dana):
    listed = sam.request("prompts/list")["result"]["prompts"]
    assert [(p["name"], [a["name"] for a in p["arguments"]]) for p in listed] == [
        ("draft_reply", ["ticket_id"])
    ]
    message = prompt(sam, "2")["result"]["messages"][0]
    assert message["role"] == "user"
    assert 'Ticket 2 [open, normal priority]: "Invoice shows the wrong plan"' in message["content"]["text"]
    refused = prompt(sam, "4")["error"]
    assert refused["code"] == -32602
    assert refused["message"].startswith("Sam Rivera can't see ticket 4:")
    assert HIDDEN in prompt(dana, "4")["result"]["messages"][0]["content"]["text"]
    assert "ticket_id must be a whole number" in prompt(sam, "two")["error"]["message"]


# The whole point.


def test_one_person_cannot_see_anothers_ticket_through_any_way_in(sam):
    # Ticket 4 is Dana's. Every kind of thing the server offers is a way in, and each one refuses.
    tool = call(sam, "get_ticket", ticket_id=4)
    resource = read(sam, "helpdesk://tickets/4")
    template = prompt(sam, "4")
    pages = [call(sam, "find_tickets", status="any", page=n) for n in (1, 2)]
    assert tool["result"]["isError"] is True
    assert "error" in resource and "error" in template
    for reply in (tool, resource, template, *pages):
        assert HIDDEN not in json.dumps(reply)


# The process: who it acts for, what goes on standard output, and shutdown.


@pytest.mark.parametrize(
    ("staff", "said"),
    [
        (None, "Refused: set HELPDESK_STAFF to the member of staff this server acts for"),
        ("bob", "Refused: No member of staff called 'bob'."),
    ],
)
def test_the_server_refuses_to_start_without_a_person_it_knows(staff, said):
    client = StdioClient(staff)
    with pytest.raises(ServerExited) as stopped:
        client.open()
    client.close()
    assert "the server exited with code 2" in str(stopped.value)
    assert said in str(stopped.value)


def test_standard_output_carries_only_mcp_messages_and_the_server_exits_when_its_input_closes():
    received: list[str] = []
    client = StdioClient("priya", wire=lambda way, line: received.append(line) if way == "<-" else None)
    try:
        client.open()
        call(client, "find_tickets")
    except json.JSONDecodeError as e:
        client.close()
        pytest.fail(f"standard output carried something that isn't a JSON-RPC message: {e.doc!r}")
    assert client.close() == 0  # closing its input is the specification's way to stop a stdio server
    assert received and all(json.loads(line)["jsonrpc"] == "2.0" for line in received)
    assert "helpdesk MCP server: acting for Priya Nair (support), on stdio." in client.stderr


def test_the_sdks_own_client_can_use_it():
    # An independent implementation of the protocol, as a host would bring its own.
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    async def session() -> tuple[str, str]:
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "helpdesk.mcp_server"], env={"HELPDESK_STAFF": "sam"}
        )
        async with Client(server) as client:
            tools = await client.list_tools()
            result = await client.call_tool("get_ticket", {"ticket_id": 4})
            return ",".join(t.name for t in tools.tools), result.content[0].text

    names, refused = anyio.run(session)
    assert names == "get_ticket,find_tickets,search_kb"
    assert refused.startswith("Sam Rivera can't see ticket 4:")


def test_the_client_command_line_shows_the_wire_and_the_result():
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "helpdesk.mcp_client",
            "--as",
            "sam",
            "--wire",
            "call",
            "get_ticket",
            "ticket_id=4",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1, run.stderr
    lines = run.stdout.splitlines()
    assert lines[0].startswith('-> {"jsonrpc": "2.0", "id": 1, "method": "server/discover"')
    assert "isError: true" in lines
    assert lines[-1].startswith("Sam Rivera can't see ticket 4:")

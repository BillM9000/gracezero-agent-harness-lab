"""A ModelClient backed by OpenAI's Responses API.

This is the only file that knows this provider's request and response shapes. It needs the openai
package and a credential the SDK can find, such as the OPENAI_API_KEY environment variable.
Everything else in the lab talks to the ModelClient protocol, so the mock, this client and the
Anthropic one are interchangeable: a definition names a model, and the gateway (helpdesk.gateway,
chapter 27) builds the adapter for the model's provider.

Read from openai 3.22.1's source and OpenAI's API reference on 2026-10-01. A response has a status
(completed, incomplete, failed, in_progress, cancelled or queued) and, when incomplete, a reason:
max_output_tokens, content_filter, max_messages or steered. Its output is a list of items: a message
whose content is output_text and refusal parts, function_call items with a call_id, a name and the
arguments as a JSON string, reasoning items, and others; usage gives input_tokens and output_tokens,
the latter counting reasoning tokens, which the API bills as output; and the SDK adds _request_id
from the x-request-id header. The lab's one shape for all of that is ModelResponse.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from helpdesk.model.types import Message, ModelResponse, StopReason, ToolCall, ToolSpec, Unavailable, Usage

# The model OpenAI's models page said to choose "to balance intelligence and cost" on 2026-10-01, the
# tier below its flagship, gpt-6-astra. The page gives this id as the model's one snapshot.
DEFAULT_MODEL = "gpt-6.1-sol"

# How an incomplete response's reason reads as the lab's stop reason. Cut off at the cap is cut off;
# stopped by the provider's filter is a refusal, since the model declined to finish. The other two
# reasons belong to flows the lab doesn't use (a cap on messages, and a WebSocket steer) and read as
# pause_turn, which final_text refuses as unfinished.
INCOMPLETE: dict[str, StopReason] = {
    "max_output_tokens": "max_tokens",
    "content_filter": "refusal",
}


def unavailable_kind(error: Exception) -> str | None:
    """Whether an error means the provider can't answer now, so another deployment or model may
    (chapter 27). openai 3.22.1's exceptions: RateLimitError is a 429 and InternalServerError any
    status from 500 up, each an APIStatusError carrying status_code; APIConnectionError, and the
    APITimeoutError built on it, carry none. The SDK has already retried each of those twice by the
    time it raises one (DEFAULT_MAX_RETRIES). Anything else, such as a malformed request, would fail
    the same way anywhere, and is raised as it is."""
    status = getattr(error, "status_code", None)
    if status == 429:
        return "rate limited"
    if isinstance(status, int) and status >= 500:
        return "server error"
    if status is None and any(kind.__name__ == "APIConnectionError" for kind in type(error).__mro__):
        return "no connection"
    return None


def retry_after(error: Exception) -> float | None:
    """The wait the provider asked for, in seconds, when its response carried a retry-after header."""
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def sdk_client_classes() -> frozenset[str]:
    """Every name the installed openai package exports for a client class: OpenAI, AsyncOpenAI, the
    Azure pair and the aliases Client and AsyncClient. Only helpdesk.model may import the SDK, so the
    one-door fitness test (chapter 27) asks here. A client class is one built on the SDK's BaseClient,
    which is private: if a new SDK moves it, this fails at once rather than finding nothing."""
    import openai
    from openai._base_client import BaseClient

    exported = ((name, getattr(openai, name)) for name in dir(openai))
    return frozenset(
        name for name, value in exported if isinstance(value, type) and issubclass(value, BaseClient)
    )


class OpenAIModel:
    def __init__(self, client: Any = None, model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> None:
        if client is None:
            import openai  # imported here so code that only uses the mock never needs the SDK

            client = openai.OpenAI()
        self._client = client
        self.model = model
        self.max_tokens = max_tokens

    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "model": self.model,
            # The cap counts every output token, reasoning tokens included (the API reference).
            "max_output_tokens": self.max_tokens,
            "instructions": system,
            "input": [item for message in messages for item in to_api(message)],
        }
        if tools:
            request["tools"] = [tool_to_api(t) for t in tools]
        try:
            response = self._client.responses.create(**request)
        except Exception as error:
            kind = unavailable_kind(error)
            if kind is None:
                raise
            raise Unavailable(kind, retry_after(error)) from error
        return read_response(response)


def read_response(response: Any) -> ModelResponse:
    """A Response as the SDK returns it, in the lab's shape. A completed response is a tool_use when
    it carries function calls, a refusal when its message holds a refusal part, and otherwise the end
    of the turn; an incomplete one reads as INCOMPLETE says. Any other status isn't an answer."""
    status = response.status
    if status not in ("completed", "incomplete"):
        error = getattr(response, "error", None)
        detail = f" ({error.code}: {error.message})" if error is not None else ""
        raise RuntimeError(
            f"OpenAI's API returned a response with status {status!r}{detail}, which isn't an answer. "
            "The lab makes no background requests, so a response is completed or incomplete when it arrives."
        )
    items = list(response.output)
    messages = [item for item in items if item.type == "message"]
    text = "".join(part.text for item in messages for part in item.content if part.type == "output_text")
    refused = any(part.type == "refusal" for item in messages for part in item.content)
    tool_calls = tuple(
        ToolCall(item.call_id, item.name, arguments_of(item))
        for item in items
        if item.type == "function_call"
    )
    stop: StopReason
    if status == "incomplete":
        reason = getattr(response.incomplete_details, "reason", None)
        stop = INCOMPLETE.get(reason, "pause_turn")
    elif tool_calls:
        stop = "tool_use"
    elif refused:
        stop = "refusal"
    else:
        stop = "end_turn"
    used = getattr(response, "usage", None)
    return ModelResponse(
        stop_reason=stop,
        text=text,
        tool_calls=tool_calls,
        raw=items,
        # What the provider counted, so a budget (chapter 23) adds up billed tokens, not guesses.
        usage=Usage(used.input_tokens, used.output_tokens) if used is not None else None,
        # The SDK's name for the provider's request-id header.
        request_id=getattr(response, "_request_id", None),
    )


def arguments_of(call: Any) -> dict[str, Any]:
    """A function call's arguments, which the API sends as a JSON string of an object."""
    try:
        arguments = json.loads(call.arguments)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{call.name}'s arguments aren't JSON ({error}): {str(call.arguments)[:120]!r}"
        ) from None
    if not isinstance(arguments, dict):
        raise ValueError(f"{call.name}'s arguments aren't a JSON object: {str(call.arguments)[:120]!r}")
    return arguments


def tool_to_api(tool: ToolSpec) -> dict[str, Any]:
    """A function tool as the Responses API takes it. strict goes out only for a schema that meets the
    API's strict mode, as the function calling guide stated it on 2026-10-01: additionalProperties
    false on every object, and every property required (an optional one is written as a null union).
    The lab's schemas keep optional properties, and the toolbox checks every argument before a tool
    runs (chapter 11), so a tool whose schema doesn't qualify is sent with strict false, which the
    guide says keeps best-effort function calling; sent as strict true, the request would be rejected
    with the missing constraints, and left out, the API would try to rewrite the schema itself."""
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
        "strict": bool(tool.strict and qualifies(tool.input_schema)),
    }


def qualifies(schema: Any) -> bool:
    """Whether strict mode accepts the schema: every object sets additionalProperties to false and
    lists every one of its properties as required, at every depth."""
    if isinstance(schema, list):
        return all(qualifies(item) for item in schema)
    if not isinstance(schema, dict):
        return True
    properties = schema.get("properties", {})
    if schema.get("type") == "object" or properties:
        if schema.get("additionalProperties") is not False:
            return False
        if set(properties) != set(schema.get("required", [])):
            return False
    # Property names are data, not keywords: only each property's own schema is looked into.
    rest = (value for key, value in schema.items() if key != "properties")
    return all(qualifies(value) for value in rest) and all(qualifies(sub) for sub in properties.values())


def to_api(message: Message) -> list[Any]:
    """One turn as the API's input items. A user turn is a message; a turn of tool results is one
    function_call_output an item, and since the API has no error flag on one (the API reference), an
    error result says so in its text; the model's own turn goes back as the items it came as,
    reasoning items included, which the function calling guide asks for, or, without them, as its
    text and function_call items."""
    if message.role == "assistant":
        if message.raw is not None:
            return list(message.raw)
        items: list[Any] = [{"role": "assistant", "content": message.content}] if message.content else []
        items += [
            {
                "type": "function_call",
                "call_id": c.id,
                "name": c.name,
                "arguments": json.dumps(c.arguments, ensure_ascii=False),
            }
            for c in message.tool_calls
        ]
        return items
    if message.tool_results:
        return [
            {
                "type": "function_call_output",
                "call_id": r.call_id,
                "output": f"Error: {r.content}" if r.is_error else r.content,
            }
            for r in message.tool_results
        ]
    return [{"role": "user", "content": message.content}]

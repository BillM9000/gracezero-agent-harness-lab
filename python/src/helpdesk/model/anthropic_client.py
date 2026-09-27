"""A ModelClient backed by Anthropic's Messages API.

This is the only file that knows the vendor's request and response shapes. It needs the anthropic
package and a credential the SDK can find, such as the ANTHROPIC_API_KEY environment variable.
Everything else in the lab talks to the ModelClient protocol, so the mock and this client are
interchangeable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from helpdesk.model.types import Message, ModelResponse, ToolCall, ToolSpec, Unavailable, Usage

# The model Anthropic's models page suggested starting with on 2026-09-22.
DEFAULT_MODEL = "claude-opus-5-5"

# Strict tool use (chapter 11), as Anthropic's structured-outputs page described it on 2026-09-23.
# It supports part of JSON Schema: not numerical constraints, string lengths, or array lengths
# beyond a minItems of 0 or 1, and a request that uses them is refused. The lab's schemas keep
# those keywords and they're left out of what is sent, because the toolbox checks minimum, maximum
# and minLength before any tool runs, and refuses to hold a tool whose schema uses any keyword or
# type it doesn't check (unchecked_rules in helpdesk/assistant/tools.py). Every object must set
# additionalProperties to false, and one request may carry at most 20 strict tools.
STRICT_UNSUPPORTED = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "maxItems",
)
MAX_STRICT_TOOLS = 20


def unavailable_kind(error: Exception) -> str | None:
    """Whether an error means the provider can't answer now, so another deployment or model may
    (chapter 27). Anthropic's errors page, read 2026-09-25: 429 rate_limit_error, 500 api_error and
    529 overloaded_error, plus no connection at all. By the time the SDK raises one, it has already
    retried it twice (DEFAULT_MAX_RETRIES in anthropic 1.8.0). Anything else, such as a malformed
    request, would fail the same way anywhere, and is raised as it is."""
    status = getattr(error, "status_code", None)
    if status == 429:
        return "rate limited"
    if status == 529:
        return "overloaded"
    if isinstance(status, int) and status >= 500:
        return "server error"
    if status is None and any(kind.__name__ == "APIConnectionError" for kind in type(error).__mro__):
        return "no connection"
    return None


def retry_after(error: Exception) -> float | None:
    """The wait the provider asked for, in seconds. A 429 at a monthly spend cap has none, and
    keeps failing until the month turns (Anthropic's rate limits page)."""
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def sdk_client_classes() -> frozenset[str]:
    """Every name the installed anthropic package exports for a client class: Anthropic, each cloud
    platform's (AnthropicBedrock, AnthropicVertex, AnthropicFoundry, ...), their async twins, and
    aliases such as Client. Only helpdesk.model may import the SDK, so the one-door fitness test
    (chapter 27) asks here. A client class is one built on the SDK's BaseClient, which is private:
    if a new SDK moves it, this fails at once rather than finding nothing."""
    import anthropic
    from anthropic._base_client import BaseClient

    exported = ((name, getattr(anthropic, name)) for name in dir(anthropic))
    return frozenset(
        name for name, value in exported if isinstance(value, type) and issubclass(value, BaseClient)
    )


class AnthropicModel:
    def __init__(self, client: Any = None, model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> None:
        if client is None:
            import anthropic  # imported here so code that only uses the mock never needs the SDK

            client = anthropic.Anthropic()
        self._client = client
        self.model = model
        self.max_tokens = max_tokens

    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [to_api(m) for m in messages],
        }
        if tools:
            strict = [t.name for t in tools if t.strict]
            if len(strict) > MAX_STRICT_TOOLS:
                raise ValueError(
                    f"{len(strict)} strict tools in one request, and strict tool use allows "
                    f"{MAX_STRICT_TOOLS}. Give the agent fewer tools, or mark only the ones where a "
                    "malformed argument does real harm as strict."
                )
            request["tools"] = [tool_to_api(t) for t in tools]
        try:
            response = self._client.messages.create(**request)
        except Exception as error:
            kind = unavailable_kind(error)
            if kind is None:
                raise
            raise Unavailable(kind, retry_after(error)) from error
        used = getattr(response, "usage", None)
        return ModelResponse(
            stop_reason=response.stop_reason,
            text="".join(block.text for block in response.content if block.type == "text"),
            tool_calls=tuple(
                ToolCall(block.id, block.name, dict(block.input))
                for block in response.content
                if block.type == "tool_use"
            ),
            raw=response.content,
            # What the provider counted, so a budget (chapter 23) adds up billed tokens, not guesses.
            usage=Usage(used.input_tokens, used.output_tokens) if used is not None else None,
            # The SDK's name for the provider's request-id header (Anthropic's errors page).
            request_id=getattr(response, "_request_id", None),
        )


def tool_to_api(tool: ToolSpec) -> dict[str, Any]:
    if not tool.strict:
        return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
    schema = strict_schema(tool.input_schema, where=tool.name)
    return {"name": tool.name, "description": tool.description, "input_schema": schema, "strict": True}


def strict_schema(schema: Any, where: str = "schema") -> Any:
    """The schema as strict tool use accepts it: the same shape, without the keywords strict mode
    doesn't support. An object that doesn't set additionalProperties to false is an error, not
    something to fix quietly: adding it here would make the model's arguments stricter than the
    schema the toolbox checks them against."""
    if isinstance(schema, list):
        return [strict_schema(item, f"{where}[{i}]") for i, item in enumerate(schema)]
    if not isinstance(schema, dict):
        return schema
    if schema.get("type") == "object" and schema.get("additionalProperties") is not False:
        raise ValueError(
            f"{where}: strict tool use needs additionalProperties set to false on every object. Add "
            '"additionalProperties": False to it, so the toolbox refuses extra arguments too.'
        )
    kept = {}
    for key, value in schema.items():
        if key in STRICT_UNSUPPORTED or (key == "minItems" and value not in (0, 1)):
            continue
        # Property names are data, not keywords: a property called "minimum" is kept.
        inside = f"{where}.{key}"
        kept[key] = (
            {name: strict_schema(sub, f"{inside}.{name}") for name, sub in value.items()}
            if key == "properties"
            else strict_schema(value, inside)
        )
    return kept


def to_api(message: Message) -> dict[str, Any]:
    if message.role == "assistant":
        if message.raw is not None:
            # Send the model's own turn back exactly as it came, including any blocks this lab
            # doesn't model, such as thinking.
            return {"role": "assistant", "content": message.raw}
        blocks: list[dict[str, Any]] = [{"type": "text", "text": message.content}] if message.content else []
        blocks += [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in message.tool_calls
        ]
        return {"role": "assistant", "content": blocks}
    if message.tool_results:
        # Every result for a turn goes back in one user message.
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content}
                | ({"is_error": True} if r.is_error else {})
                for r in message.tool_results
            ],
        }
    return {"role": "user", "content": message.content}

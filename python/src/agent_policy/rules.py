"""The policy for agent definitions (chapter 18), as one pure function: check(definition, policy).

It takes a parsed definition and the parsed policy, and returns every violation it finds, each
naming the field and giving the reason and the fix, so a definition with three problems gets three
messages in one run. It reads no files, calls nothing and keeps no state, which is what lets the
fixtures in tests/policy_fixtures/ pin exactly what it accepts and what it refuses.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Every rule the policy applies. A test requires each one to be shown failing by some fixture.
RULES = {
    "unknown-field": "a field that agent definitions don't have",
    "missing": "a required field left out",
    "type": "a field of the wrong type",
    "empty": "a text field left empty",
    "range": "a limit below 1",
    "model": "a model the platform hasn't approved",
    "cost": "max_tokens that could cost more per call than the policy allows",
    "turns": "max_turns above the policy's limit",
    "tool": "a tool the platform doesn't provide",
    # Chapter 19: tools that change things.
    "approval": "a tool that changes things, given without saying whose approval it needs",
    "approver": "an approval the platform doesn't know",
    "approval-level": "an approval below the least the platform requires for that tool",
    "approval-extra": "an approval for a tool that only reads, or that the agent doesn't have",
}


@dataclass(frozen=True)
class Violation:
    path: str  # the field as it's written in the file, such as "max_tokens" or "tools[1]"
    rule: str  # which rule it breaks, so tests and reports can group them
    reason: str  # what's wrong, and what to do about it

    def __post_init__(self) -> None:
        if self.rule not in RULES:
            raise ValueError(f"{self.rule!r} isn't in RULES; add it, with a fixture that shows it failing.")


# Every field an agent definition has, its type, and why the platform needs it.
FIELDS: dict[str, tuple[type, str]] = {
    "name": (str, "Name the agent, so its runs and its costs can be told apart."),
    "owner": (str, "Name the team that answers for the agent when it misbehaves."),
    "model": (str, "Say which model the agent calls."),
    "max_tokens": (int, "Cap how much each model call may write."),
    "max_turns": (int, "Cap how many turns one run may take."),
    "tools": (list, "List the tools the agent may use; an empty list means none."),
    "system": (str, "Give the agent its system prompt."),
}
# Fields a definition may leave out. approval becomes required once the agent has a tool that
# changes things (chapter 19): the rules below say which.
OPTIONAL: dict[str, tuple[type, str]] = {
    "approval": (dict, "Say whose approval each tool that changes things needs."),
}
TYPE_NAMES = {str: "text", int: "a whole number", list: "a list", dict: "a table, such as [approval]"}


def shown(value: Any) -> str:
    """A value as a definition file writes it: true, "6", ["get_ticket"]."""
    return json.dumps(value, ensure_ascii=False)


def is_a(value: Any, kind: type) -> bool:
    # In Python, True is an int. In a definition it's a mistake.
    return isinstance(value, kind) and not isinstance(value, bool)


def check(definition: dict[str, Any], policy: dict[str, Any]) -> list[Violation]:
    found: list[Violation] = []

    known = [*FIELDS, *OPTIONAL]
    for key in definition:
        if key not in known:
            close = difflib.get_close_matches(key, known, n=1)
            hint = f"Did you mean {close[0]}?" if close else f"The fields are {', '.join(known)}."
            reason = f"{key} isn't a field of an agent definition. {hint}"
            found.append(Violation(key, "unknown-field", reason))

    usable: dict[str, Any] = {}
    for key, (kind, why) in {**FIELDS, **OPTIONAL}.items():
        if key not in definition:
            if key in FIELDS:
                found.append(Violation(key, "missing", f"missing. {why}"))
        elif not is_a(definition[key], kind):
            found.append(Violation(key, "type", f"must be {TYPE_NAMES[kind]}, not {shown(definition[key])}."))
        elif kind is str and not definition[key].strip():
            found.append(Violation(key, "empty", f"is empty. {why}"))
        else:
            usable[key] = definition[key]

    models: dict[str, dict[str, float]] = policy["models"]
    model = usable.get("model")
    if model is not None and model not in models:
        found.append(
            Violation(
                "model",
                "model",
                f"{shown(model)} isn't an approved model. Use one of {', '.join(map(shown, models))}, or ask "
                "the platform team to approve it in agents/policy.toml.",
            )
        )

    max_tokens = usable.get("max_tokens")
    if max_tokens is not None and max_tokens < 1:
        found.append(Violation("max_tokens", "range", f"must be at least 1, not {max_tokens}."))
    elif max_tokens is not None and model in models:
        # A rule across two fields: what a call may cost depends on the model's price.
        price = Decimal(str(models[model]["output_usd_per_million"]))
        cap = Decimal(str(policy["max_call_output_usd"]))
        cost = price * max_tokens / 1_000_000
        if cost > cap:
            most = int(cap * 1_000_000 / price)
            found.append(
                Violation(
                    "max_tokens",
                    "cost",
                    f"{max_tokens:,} output tokens from {model} could cost ${cost:.2f} a call, and the "
                    f"policy allows ${cap:.2f}. Lower max_tokens to {most:,} or less, or use a cheaper "
                    "approved model.",
                )
            )

    max_turns = usable.get("max_turns")
    limit = policy["max_turns"]
    if max_turns is not None and max_turns < 1:
        found.append(Violation("max_turns", "range", f"must be at least 1, not {max_turns}."))
    elif max_turns is not None and max_turns > limit:
        found.append(
            Violation(
                "max_turns",
                "turns",
                f"{max_turns} is more than the policy's limit of {limit}. An agent that needs more turns "
                "is trying to do too much in one run: split the task, or ask the platform team for a "
                "higher limit.",
            )
        )

    for i, tool in enumerate(usable.get("tools", [])):
        if not is_a(tool, str):
            found.append(Violation(f"tools[{i}]", "type", f"must be a tool's name, not {shown(tool)}."))
        elif tool not in policy["tools"]:
            found.append(
                Violation(
                    f"tools[{i}]",
                    "tool",
                    f"{shown(tool)} isn't a tool the platform provides. "
                    f"The tools are {', '.join(map(shown, policy['tools']))}.",
                )
            )

    # Chapter 19: a tool that changes things needs a named approval, at least the policy's.
    writes: dict[str, str] = policy["writes"]
    levels: list[str] = policy["approvers"]
    tools = [tool for tool in usable.get("tools", []) if is_a(tool, str)]
    approval = usable.get("approval")
    if approval is None and "approval" in definition:
        return found  # approval is there but isn't a table, which is reported above
    approval = approval or {}
    for tool in tools:
        if tool in writes and tool not in approval:
            least = shown(writes[tool])
            reason = (
                f"missing. {tool} changes things, so the definition must say whose approval a change "
                f"needs before it happens: add {tool} = {least} under [approval], or a higher approval."
            )
            found.append(Violation(f"approval.{tool}", "approval", reason))
    for tool, who in approval.items():
        at = f"approval.{tool}"
        if tool not in writes:
            reason = f"{tool} doesn't change anything, so it needs no approval. Remove this line."
            found.append(Violation(at, "approval-extra", reason))
        elif tool not in tools:
            reason = f"{tool} isn't one of this agent's tools. Remove this line, or add {tool} to tools."
            found.append(Violation(at, "approval-extra", reason))
        elif not is_a(who, str):
            found.append(Violation(at, "type", f"must be text, one of {', '.join(map(shown, levels))}."))
        elif who not in levels:
            known_levels = ", ".join(map(shown, levels))
            reason = f"{shown(who)} isn't an approval the platform knows. Use one of {known_levels}."
            found.append(Violation(at, "approver", reason))
        elif levels.index(who) < levels.index(writes[tool]):
            reason = (
                f"{shown(who)} is less than {tool} needs: the platform requires at least "
                f"{shown(writes[tool])}. Raise it, or ask the platform team to change agents/policy.toml."
            )
            found.append(Violation(at, "approval-level", reason))

    return found

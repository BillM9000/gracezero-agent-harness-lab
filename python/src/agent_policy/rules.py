"""The policy for agent definitions (chapter 18), as one pure function:
check(definition, policy, models, today).

It takes a parsed definition, the parsed policy, the models' lifecycle (agents/models.toml, chapter
20) and the day to check as of, and returns every violation it finds, each naming the field and
giving the reason and the fix, so a definition with three problems gets three messages in one run.
It reads no files and no clock, calls nothing and keeps no state, which is what lets the fixtures in
tests/policy_fixtures/ pin exactly what it accepts and what it refuses, on any day.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from datetime import date
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
    # Chapter 20: models as components with a retirement date.
    "retired": "a model that has retired, so requests to it fail",
    "retiring": "a model that is deprecated, or may retire within the policy's notice",
    # Chapter 27: what an agent spends is its owner's, against the team's monthly budget.
    "team": "an owner that isn't a team the platform knows, so nothing limits what it spends",
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


def tracked(models: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every model agents/models.toml tracks, from every provider's section, each entry with its
    provider (the section's key, and its name as the page writes it), the page it was copied from and
    the day it was read, so a report can say whose page and when. A model listed under two providers
    is an error, not a choice."""
    entries: dict[str, dict[str, Any]] = {}
    for provider, section in models.items():
        for model, entry in section["models"].items():
            if model in entries:
                first = entries[model]["provider"]
                raise ValueError(
                    f"agents/models.toml lists {model} under {first} and {provider}: a model has one "
                    "provider, so keep it under that provider's section alone."
                )
            entries[model] = {
                **entry,
                "provider": provider,
                "provider_name": section["name"],
                "page": section["page"],
                "read": section["read"],
            }
    return entries


def lifecycle(model: str, policy: dict[str, Any], models: dict[str, Any], today: date) -> Violation | None:
    """Chapter 20: a model that has retired, is deprecated, or may retire within the policy's notice,
    with the date and what to move to. None for a model that's fine, or that the registry doesn't
    know (check reports that separately for an approved model)."""
    registry = tracked(models)
    entry = registry.get(model)
    if entry is None:
        return None
    state, retires = entry["state"], entry.get("retires")
    approved: dict[str, Any] = policy["models"]
    notice: int = policy["retirement_notice_days"]
    replacement = entry.get("replacement")
    if replacement is not None:
        move = f"{entry['provider_name']} recommends {replacement} in its place"
        move += (
            ", which is approved: change model to it."
            if replacement in approved
            else f", which isn't approved here: use one of {', '.join(map(shown, approved))}, or ask the "
            "platform team to approve it in agents/policy.toml."
        )
    else:
        # The approved models that may retire later than this one, and aren't retiring themselves.
        def later(other: str) -> bool:
            theirs = registry.get(other, {})
            when = theirs.get("retires")
            return (
                theirs.get("state") == "active"
                and when is not None
                and (retires is None or when > retires)
                and (when - today).days > notice
            )

        # And the approved, active models whose provider has announced no retirement at all: later
        # than this one is unknown, not known, so they're named rather than suggested.
        def undated(other: str) -> bool:
            theirs = registry.get(other, {})
            return theirs.get("state") == "active" and theirs.get("retires") is None

        better = [m for m in approved if m != model and later(m)]
        unannounced = [m for m in approved if m != model and undated(m)]
        if better:
            move = f"Move to an approved model that retires later: {', '.join(map(shown, better))}."
        elif unannounced:
            named = ", ".join(map(shown, unannounced))
            has = "has" if len(unannounced) == 1 else "have"
            move = (
                f"No approved model has a later retirement date announced, and {named} {has} none "
                "announced: ask the platform team which to move to, or to approve a newer one."
            )
        else:
            move = "No approved model retires later: ask the platform team to approve a newer one."
    read = f"(agents/models.toml, from {entry['provider_name']}'s {entry['page']}, read {entry['read']})"
    if state == "retired" or (state == "deprecated" and retires is not None and retires <= today):
        when = f" on {retires.isoformat()}" if retires is not None else ""
        return Violation("model", "retired", f"{model} retired{when}, and requests to it fail {read}. {move}")
    if state == "deprecated":
        if retires is None:
            reason = f"{model} is deprecated, and its retirement date isn't announced yet {read}. {move}"
        else:
            days = (retires - today).days
            reason = (
                f"{model} is deprecated and retires on {retires.isoformat()}, in {days} days {read}. {move}"
            )
        return Violation("model", "retiring", reason)
    if retires is not None and (retires - today).days <= notice:
        days = (retires - today).days
        soon = f"in {days} days" if days >= 0 else f"{-days} days ago"
        reason = (
            f"{model} may retire as soon as {retires.isoformat()}, {soon}, and the policy moves agents "
            f"{notice} days before {read}. {move}"
        )
        return Violation("model", "retiring", reason)
    return None


def check(
    definition: dict[str, Any], policy: dict[str, Any], models: dict[str, Any], today: date
) -> list[Violation]:
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

    # Chapter 27: the owner pays, so the owner must be a team with a budget the gateway can hold.
    owner = usable.get("owner")
    teams: dict[str, Any] = policy["teams"]
    if owner is not None and owner not in teams:
        close = difflib.get_close_matches(owner, list(teams), n=1)
        hint = (
            f"Did you mean {shown(close[0])}?" if close else f"The teams are {', '.join(map(shown, teams))}."
        )
        reason = (
            f"{shown(owner)} isn't a team the platform knows, so nothing would limit what this agent "
            f"spends. {hint} A new team needs a monthly budget under [teams] in agents/policy.toml."
        )
        found.append(Violation("owner", "team", reason))

    approved: dict[str, dict[str, float]] = policy["models"]
    model = usable.get("model")
    if model is not None and model not in approved:
        found.append(
            Violation(
                "model",
                "model",
                f"{shown(model)} isn't an approved model. Use one of {', '.join(map(shown, approved))}, or "
                "ask the platform team to approve it in agents/policy.toml.",
            )
        )
    elif model is not None and model not in tracked(models):
        # Approved, but nobody tracks when it retires. Fail closed.
        found.append(
            Violation(
                "model",
                "model",
                f"{shown(model)} is approved but isn't in agents/models.toml, so nothing tracks when it "
                "retires. Add it under its provider's section, from that provider's deprecations page.",
            )
        )
    if model is not None:
        retiring = lifecycle(model, policy, models, today)
        if retiring is not None:
            found.append(retiring)

    max_tokens = usable.get("max_tokens")
    if max_tokens is not None and max_tokens < 1:
        found.append(Violation("max_tokens", "range", f"must be at least 1, not {max_tokens}."))
    elif max_tokens is not None and model in approved:
        # A rule across two fields: what a call may cost depends on the model's price.
        price = Decimal(str(approved[model]["output_usd_per_million"]))
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

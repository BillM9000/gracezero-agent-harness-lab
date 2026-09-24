"""Text the company didn't write (chapter 20): marked as data where the model reads it, and flagged
for the person who approves when it's shaped like an instruction.

Anyone who can open a ticket can write text the triage assistant will read, and a model can't
reliably tell an instruction to follow from text that only looks like one. So:

- Everything a customer typed (a ticket's subject and text, and their replies) reaches the model
  only inside a tool result, as a JSON string, with a label saying who wrote it. Anthropic's guidance
  on indirect prompt injection advises all three. A JSON string can't be closed from inside, because
  its quotes and line breaks are escaped, so the text can't break out of its marking.
- flag() looks for text shaped like an instruction. It's a flag for the person who approves a change,
  never a gate: a list of phrases can't catch every way of writing an instruction, and
  evals/injections.json records ones it misses.

Neither makes a hijacked model safe. What does is that what the assistant may do never depends on
what it read: its tools act for one person and check what that person may change (access.py), a
change waits for a person's approval (proposals.py), and no tool sends anything outside the
helpdesk (tests/fitness/test_nothing_sends_outside.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Instruction-shaped text, each pattern named for what it catches. Matching is on words, without
# case, within one line. Add a pattern when a red-team case shows one missing, and record the case
# in evals/injections.json either way.
PATTERNS: dict[str, re.Pattern[str]] = {
    # "Ignore your previous instructions", "disregard the rules above".
    "override": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(instructions?|rules|prompt|guidelines)\b", re.I
    ),
    # Text that claims to come from the system, an administrator or the developer.
    "claimed-authority": re.compile(
        r"\b(system|admin|administrator|developer|operator)\s+(note|message|notice|override|prompt)\b"
        r"|^\s*(system|assistant)\s*:",
        re.I | re.M,
    ),
    # Text addressed to the model rather than to a person.
    "addressed-to-the-model": re.compile(
        r"\b(to|for|attention)\s+(the\s+)?(ai|assistant|agent|bot|model|llm)\b", re.I
    ),
    # An action on everything at once: "close every ticket", "reply with all customers".
    "sweeping-action": re.compile(
        r"\b(close|delete|approve|send|forward|export|list|reply)\b[^.\n]{0,40}\b(every|all)\b[^.\n]{0,30}"
        r"\b(tickets?|customers?|emails?|addresses|users?|records?)\b",
        re.I,
    ),
    # Sending something to an address outside the helpdesk.
    "send-elsewhere": re.compile(r"\b(send|post|upload|forward|copy)\b[^\n]{0,80}\bhttps?://", re.I),
    # Asking for secrecy from the person.
    "secrecy": re.compile(r"\b(don't|do not|never)\s+(tell|mention|inform|show)\b", re.I),
}


def quoted(text: str) -> str:
    """Text a customer wrote, as a JSON string: quotes, backslashes and line breaks escaped, so
    nothing inside can end the string early."""
    return json.dumps(text, ensure_ascii=False)


def flag(text: str) -> list[str]:
    """The instruction-shaped phrases in the text, each with the pattern that found it, such as
    'override: "ignore your previous instructions"'. Empty when nothing matches, which proves
    nothing: see the module's docstring."""
    found = []
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            found.append(f"{name}: {quoted(' '.join(match.group(0).split()))}")
    return found


@dataclass(frozen=True)
class Flag:
    """One instruction-shaped phrase the agent read, and where."""

    source: str  # such as "ticket 13, written by the customer"
    phrase: str  # what flag() returned


@dataclass
class Exposure:
    """What one run of an agent has read that someone outside the company wrote, and what flag()
    found in it. The tools that read add to it; the tools that write copy its flags onto every
    proposal they file, so the person deciding sees what the agent had read before it asked."""

    flags: list[Flag] = field(default_factory=list)

    def read(self, source: str, *texts: str) -> None:
        for text in texts:
            for phrase in flag(text):
                if Flag(source, phrase) not in self.flags:
                    self.flags.append(Flag(source, phrase))

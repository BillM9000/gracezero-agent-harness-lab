"""The central team's intake and readiness gate (chapter 28).

The rules take their evidence as arguments, so most tests build it by hand from the lab's real data
and change one thing. The last tests run the command over the lab's own use cases, and over copies
of them in a temporary folder with one thing changed. The last section covers chapter 29's
exceptions. Nothing here calls a model.
"""

from __future__ import annotations

import copy
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent_policy import POLICY, today
from agent_policy import load as load_toml
from helpdesk import readiness as command
from readiness import LIBRARY, READINESS, RUBRIC, USE_CASES, load
from readiness.rules import CHECKS, Evidence, Promotion, fingerprint, floors, review, score, tier_of

RUBRIC_DATA = load(RUBRIC)
READINESS_DATA = load(READINESS)
LIBRARY_NAMES = frozenset(c["name"] for c in load(LIBRARY)["capabilities"])
TRIAGE = load(USE_CASES / "triage-assistant.toml")
DEFINITIONS = command.definitions()
INJECTIONS = {f"case-{i}": 5 for i in range(16)}


def evidence(**changes: Any) -> Evidence:
    """The lab's evidence as the tests assume it: every definition passes the policy, and the last
    promotion covers the triage assistant and is current."""
    base: dict[str, Any] = {
        "definitions": DEFINITIONS,
        "policy": {name: [] for name in DEFINITIONS},
        "promotion": Promotion("2026-09-25", "the mock", frozenset({"triage", "judge"}), True, 5, INJECTIONS),
        "servers": frozenset({"helpdesk"}),
        "teams": frozenset({"support-tools"}),
        "today": today(),
    }
    base.update(changes)
    return Evidence(**base)


def signed(record: dict[str, Any], definition: dict[str, Any] | None = None) -> dict[str, Any]:
    """The record with its sign-offs' fingerprints brought up to date, as if reviewed again."""
    record = copy.deepcopy(record)
    now = fingerprint(record, definition if definition is not None else DEFINITIONS.get(record.get("agent")))
    for s in record.get("signoffs", []):
        s["fingerprint"] = now
    return record


def results(record: dict[str, Any], found: Evidence | None = None) -> dict[str, tuple[bool, str]]:
    r = review(record, RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, found or evidence())
    assert not r.problems, r.problems
    return {res.item: (res.ok, res.detail) for res in r.results}


def test_the_lab_use_case_in_production_is_ready():
    r = review(TRIAGE, RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence())
    assert r.ready and r.passes
    assert [res.item for res in r.results] == list(CHECKS)


def test_every_checklist_item_has_a_check_and_every_check_an_item():
    assert command.checklist_problems(READINESS_DATA) == []
    assert [item["id"] for item in READINESS_DATA["items"]] == list(CHECKS)
    extra = {"items": [*READINESS_DATA["items"], {"id": "load-test", "what": "", "tiers": ["high"]}]}
    assert command.checklist_problems(extra) == [
        "usecases/readiness.toml: load-test: no check in src/readiness/rules.py."
    ]


def test_every_capability_names_a_module_that_exists():
    library = load(LIBRARY)
    assert command.library_problems(library) == []
    planted = {"capabilities": [{"name": "customer-email", "provided_by": "helpdesk.email"}]}
    [problem] = command.library_problems(planted)
    assert "customer-email: provided_by helpdesk.email isn't a module here" in problem


def test_the_answers_score_the_tier():
    scored, problems = score({"acts": "changes", "data": "customer", "audience": "staff"}, RUBRIC_DATA)
    assert problems == [] and scored is not None
    assert (scored.score, scored.tier) == (5, "high")
    assert scored.line() == "acts changes 3, data customer 2, audience staff 0: 5, high"
    assert [tier_of(n, RUBRIC_DATA) for n in range(7)] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
        "high",
    ]


def test_a_missing_or_unknown_answer_is_named_and_nothing_is_scored():
    scored, problems = score({"acts": "writes", "data": "customer", "mood": "calm"}, RUBRIC_DATA)
    assert scored is None
    assert problems == [
        "intake.mood: isn't a question in usecases/rubric.toml.",
        'intake.acts: "writes" isn\'t an answer. Use one of reads, drafts, changes.',
        "intake.audience: missing. Who reads what it writes before a person has checked it? "
        "One of staff, customers.",
    ]


def test_an_agents_tools_set_the_least_answer_and_the_strictest_tool_wins():
    # draft_reply comes before close_ticket in the triage assistant's tools; close_ticket's floor wins.
    assert floors(DEFINITIONS["triage"], RUBRIC_DATA) == {
        "data": ("customer", "get_ticket"),
        "acts": ("changes", "close_ticket"),
    }
    for said in ("reads", "drafts"):
        record = signed({**TRIAGE, "intake": {**TRIAGE["intake"], "acts": said}})
        ok, detail = results(record)["triaged"]
        assert not ok
        assert detail.startswith(f"intake.acts says {said}, but agents/triage.toml gives it close_ticket")


def test_the_floors_cover_every_tool_that_changes_something():
    writes = load_toml(POLICY)["writes"]
    for tool in writes:
        assert RUBRIC_DATA["floors"][tool]["acts"] != "reads", tool
    for tool, questions in RUBRIC_DATA["floors"].items():
        assert tool in load_toml(POLICY)["tools"]
        for question, least in questions.items():
            assert least in RUBRIC_DATA["questions"][question]["answers"]


def test_a_recorded_tier_that_isnt_the_rubrics_fails():
    record = signed({**TRIAGE, "tier": "medium"})
    ok, detail = results(record)["triaged"]
    assert not ok
    assert detail.startswith("records medium, but its answers score acts changes 3")


def test_a_need_outside_the_library_is_left_for_the_platform_team():
    record = signed({**TRIAGE, "needs": [*TRIAGE["needs"], "customer-email"]})
    ok, detail = results(record)["library"]
    assert not ok and detail.startswith('"customer-email" isn\'t in the library')


def test_the_policy_item_carries_the_policys_reason():
    found = evidence(policy={"triage": ["max_turns: 12 is more than the policy's limit of 10.", "another"]})
    ok, detail = results(TRIAGE, found)["policy"]
    assert not ok
    assert detail == (
        "agents/triage.toml breaks the platform's policy: "
        "max_turns: 12 is more than the policy's limit of 10. (and 1 more)"
    )


def test_a_server_not_in_the_catalog_fails():
    record = signed({**TRIAGE, "servers": ["helpdesk", "crm"]})
    ok, detail = results(record)["servers"]
    assert not ok and detail.startswith('"crm" isn\'t in catalog/servers.toml')


def test_promotion_needs_the_agent_in_a_promotion_that_is_still_current():
    ok, detail = results(TRIAGE, evidence(promotion=None))["promotion"]
    assert not ok and detail.startswith("nothing has been promoted")
    other = Promotion("2026-09-25", "the mock", frozenset({"judge"}), True, 5, INJECTIONS)
    ok, detail = results(TRIAGE, evidence(promotion=other))["promotion"]
    assert not ok and detail.startswith("agents/triage.toml isn't in the promotion of 2026-09-25")
    stale = Promotion("2026-09-25", "the mock", frozenset({"triage"}), False, 5, INJECTIONS)
    ok, detail = results(TRIAGE, evidence(promotion=stale))["promotion"]
    assert not ok and "measured has changed since" in detail


def test_red_team_needs_every_case_to_pass_every_trial():
    one_miss = Promotion(
        "2026-09-25", "the mock", frozenset({"triage"}), True, 5, {**INJECTIONS, "encoded": 4}
    )
    ok, detail = results(TRIAGE, evidence(promotion=one_miss))["red-team"]
    assert not ok and detail == "1 of 17 red-team cases failed a trial at the promotion"
    none_run = Promotion("2026-09-25", "the mock", frozenset({"triage"}), True, 5, {})
    ok, _ = results(TRIAGE, evidence(promotion=none_run))["red-team"]
    assert not ok


def test_a_sign_off_counts_only_from_a_reviewer_who_isnt_the_champion_for_what_ships():
    def with_security(**changes: Any) -> dict[str, Any]:
        record = signed(TRIAGE)
        record["signoffs"][1].update(changes)
        return record

    ok, detail = results({**signed(TRIAGE), "signoffs": signed(TRIAGE)["signoffs"][:1]})["sign-off"]
    assert not ok and detail == "needs a security reviewer's sign-off"
    ok, detail = results(with_security(by="Sam Rivera"))["sign-off"]
    assert not ok and detail == "Sam Rivera isn't a security reviewer in usecases/readiness.toml"
    champion = signed({**TRIAGE, "champion": "Jordan Okafor"})
    ok, detail = results(champion)["sign-off"]
    assert not ok and "is its champion" in detail
    ok, detail = results(with_security(fingerprint="sha256:0"))["sign-off"]
    assert not ok and detail.startswith(
        "security's sign-off by Jordan Okafor on 2026-09-25 was for something else"
    )


def test_a_change_to_the_agent_after_sign_off_needs_a_new_one():
    changed = {**DEFINITIONS, "triage": {**DEFINITIONS["triage"], "max_turns": 5}}
    ok, detail = results(TRIAGE, evidence(definitions=changed))["sign-off"]
    assert not ok and "was for something else" in detail


def test_the_fingerprint_leaves_out_only_the_stage_and_the_sign_offs():
    definition = DEFINITIONS["triage"]
    now = fingerprint(TRIAGE, definition)
    assert fingerprint({**TRIAGE, "stage": "building", "signoffs": []}, definition) == now
    assert fingerprint({**TRIAGE, "problem": "Something else."}, definition) != now
    assert fingerprint(TRIAGE, {**definition, "system": "Be brief."}) != now


def test_only_a_use_case_in_production_must_be_ready():
    building = {**TRIAGE, "stage": "building", "signoffs": []}
    r = review(building, RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence())
    assert not r.ready and r.passes
    r = review({**building, "stage": "production"}, RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence())
    assert not r.ready and not r.passes


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"owner": "support-tools"}, "owner: isn't a field of a use case."),
        ({"stage": "live"}, 'stage: "live" isn\'t a stage.'),
        ({"team": "billing"}, 'team: "billing" isn\'t a team in agents/policy.toml'),
        ({"tier": None}, "tier: missing. A use case past proposed records the tier its triage gave."),
        ({"agent": None}, "agent: missing. A use case in production names its agent definition."),
        ({"signoffs": [{"role": "platform"}]}, "signoffs[0]: needs by, on, fingerprint."),
    ],
)
def test_a_malformed_record_fails_at_any_stage(change, expected):
    record = {k: v for k, v in {**TRIAGE, **change}.items() if v is not None}
    r = review(record, RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence())
    assert not r.passes
    assert any(p.startswith(expected) for p in r.problems), r.problems


def test_the_promotion_is_current_only_while_nothing_it_measured_changed(monkeypatch):
    found = command.promotion()
    assert found is not None and found.current and "triage" in found.agents
    real = command.gate.configuration

    def changed() -> dict[str, str]:
        return {**real(), "evals/tasks.json: a golden set": "0"}

    monkeypatch.setattr(command.gate, "configuration", changed)
    found = command.promotion()
    assert found is not None and not found.current


def test_the_check_passes_on_the_lab_and_says_whats_left(capsys):
    assert command.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "triage-assistant: production, high (score 5)" in out
    assert "  left  promotion  agents/orchestrator.toml isn't in the promotion" in out
    assert out.rstrip().endswith("2 more on the way, with 8 item(s) left between them.")


def lab_copy(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "usecases"
    shutil.copytree(USE_CASES, folder)
    monkeypatch.setattr(command, "USE_CASES", folder)
    return folder


def test_the_check_fails_when_a_use_case_in_production_changes(tmp_path, monkeypatch, capsys):
    folder = lab_copy(tmp_path, monkeypatch)
    path = folder / "triage-assistant.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace('acts = "changes"', 'acts = "reads"'), encoding="utf-8"
    )
    assert command.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "triage-assistant: production, recorded high, though its answers score 2, medium" in out
    assert "  left  triaged    intake.acts says reads, but agents/triage.toml gives it close_ticket" in out
    assert "  usecases/triage-assistant.toml: it's in production and not ready." in out


def test_the_check_fails_on_a_record_it_cant_read(tmp_path, monkeypatch, capsys):
    folder = lab_copy(tmp_path, monkeypatch)
    (folder / "broken.toml").write_text('name = "broken"\nstage = \n', encoding="utf-8")
    assert command.main(["check"]) == 1
    assert "usecases/broken.toml: isn't valid TOML" in capsys.readouterr().out


def test_triage_prints_the_score_the_path_and_what_the_library_lacks(capsys):
    assert command.main(["triage", str(USE_CASES / "renewal-reminders.toml")]) == 0
    out = capsys.readouterr().out
    assert "  Score 6: high. Central:" in out
    assert "  Before production: triaged, library, policy, servers, promotion, red-team, sign-off." in out
    assert "  Not in the library: customer-email." in out


def test_triage_refuses_a_recorded_tier_that_isnt_the_rubrics(tmp_path, capsys):
    path = tmp_path / "low.toml"
    text = (
        (USE_CASES / "customer-digest.toml")
        .read_text(encoding="utf-8")
        .replace('tier = "medium"', 'tier = "low"')
    )
    path.write_text(text, encoding="utf-8")
    assert command.main(["triage", str(path)]) == 1
    assert "  It records low: change tier to medium." in capsys.readouterr().out


def test_fingerprint_prints_what_the_sign_offs_in_the_lab_carry(capsys):
    assert command.main(["fingerprint", str(USE_CASES / "triage-assistant.toml")]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == TRIAGE["signoffs"][0]["fingerprint"] == TRIAGE["signoffs"][1]["fingerprint"]


# --- Chapter 29: exceptions a reviewer gives, each with a reason and a day it ends.

STALE = Promotion("2026-09-25", "the mock", frozenset({"triage", "judge"}), False, 5, INJECTIONS)


def excepted(**changes: Any) -> dict[str, Any]:
    """The triage assistant with one exception for its promotion, given by a platform reviewer."""
    exception = {
        "item": "promotion",
        "reason": "The judge's rubric changed; a paid run re-promotes it this sprint.",
        "by": "Alex Moreno",
        "on": date(2026, 9, 20),
        "until": date(2026, 10, 1),
    }
    exception.update(changes)
    return {**TRIAGE, "exceptions": [exception]}


def test_an_exception_excuses_an_item_until_the_day_it_ends():
    r = review(excepted(), RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence(promotion=STALE))
    assert r.ready and r.passes
    [promoted] = [res for res in r.results if res.item == "promotion"]
    assert promoted.ok and promoted.excused
    assert promoted.detail.startswith("by Alex Moreno until 2026-10-01: The judge's rubric changed;")
    assert "Without it: something the promotion of 2026-09-25 measured has changed since" in promoted.detail
    on_the_last_day = evidence(promotion=STALE, today=date(2026, 10, 1))
    assert review(excepted(), RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, on_the_last_day).ready
    after = evidence(promotion=STALE, today=date(2026, 10, 2))
    r = review(excepted(), RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, after)
    assert not r.ready and not r.passes
    [promoted] = [res for res in r.results if res.item == "promotion"]
    assert not promoted.ok and not promoted.excused
    assert promoted.detail.startswith("its exception ended on 2026-10-01: something the promotion")


def test_an_exception_with_nothing_to_excuse_fails():
    r = review(excepted(), RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence())
    assert not r.passes
    assert r.problems == ["exceptions[0]: promotion passes now, so there's nothing to excuse. Remove it."]
    digest = load(USE_CASES / "customer-digest.toml")
    record = {**digest, "exceptions": [{**excepted()["exceptions"][0], "item": "red-team"}]}
    r = review(record, RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence())
    assert r.problems == ["exceptions[0]: its tier doesn't ask for red-team, so there's nothing to excuse."]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"item": "sign-off"}, 'exceptions[0]: "sign-off" can\'t be excused; only library, servers,'),
        ({"item": "policy"}, 'exceptions[0]: "policy" can\'t be excused;'),
        ({"reason": "  "}, "exceptions[0]: reason is empty."),
        ({"by": "Sam Rivera"}, "exceptions[0]: Sam Rivera isn't a reviewer in usecases/readiness.toml."),
        ({"by": "Dana Whitfield"}, "exceptions[0]: Dana Whitfield isn't a reviewer"),
        (
            {"until": date(2026, 10, 21)},
            "exceptions[0]: runs from 2026-09-20 to 2026-10-21. An exception ends",
        ),
        ({"until": date(2026, 9, 20)}, "exceptions[0]: runs from 2026-09-20 to 2026-09-20."),
        ({"on": "yesterday"}, "exceptions[0]: on and until must be dates"),
        ({"until": None}, "exceptions[0]: needs until."),
    ],
)
def test_a_malformed_exception_fails_at_any_stage(change, expected):
    exception = {k: v for k, v in {**excepted()["exceptions"][0], **change}.items() if v is not None}
    for stage in ("building", "production"):
        record = {**TRIAGE, "stage": stage, "exceptions": [exception]}
        r = review(record, RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence(promotion=STALE))
        assert not r.passes
        assert any(p.startswith(expected) for p in r.problems), r.problems


def test_a_champion_cant_excuse_their_own_use_case():
    record = {**excepted(), "champion": "Alex Moreno"}
    r = review(record, RUBRIC_DATA, READINESS_DATA, LIBRARY_NAMES, evidence(promotion=STALE))
    assert r.problems == ["exceptions[0]: Alex Moreno is its champion, and can't excuse their own use case."]


def test_an_exception_leaves_the_fingerprint_alone():
    definition = DEFINITIONS["triage"]
    assert fingerprint(excepted(), definition) == fingerprint(TRIAGE, definition)


def test_the_check_shows_an_excused_item_and_judges_it_on_the_day_given(tmp_path, monkeypatch, capsys):
    folder = lab_copy(tmp_path, monkeypatch)
    path = folder / "triage-assistant.toml"
    exception = (
        '\n[[exceptions]]\nitem = "promotion"\nreason = "A paid run re-promotes it."\n'
        'by = "Alex Moreno"\non = 2026-09-25\nuntil = 2026-10-09\n'
    )
    path.write_text(path.read_text(encoding="utf-8") + exception, encoding="utf-8")
    real = command.gate.configuration
    monkeypatch.setattr(command.gate, "configuration", lambda: {**real(), "evals/judged.json": "0"})
    assert command.main(["check", "--today", "2026-10-09"]) == 0
    out = capsys.readouterr().out
    assert "  excused  promotion  by Alex Moreno until 2026-10-09: A paid run re-promotes it." in out
    assert "  ok       red-team   all 16 red-team cases passed 5 of 5 trials" in out
    assert command.main(["check", "--today", "2026-10-10"]) == 1
    out = capsys.readouterr().out
    assert "  left  promotion  its exception ended on 2026-10-09: something the promotion" in out
    assert "  usecases/triage-assistant.toml: it's in production and not ready." in out

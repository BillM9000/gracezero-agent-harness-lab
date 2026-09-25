"""The golden path (chapter 29): a use case started on it passes the platform's checks from its first
commit, no answer can change the shape of what it writes, and the golden state says which use cases
are on it. Nothing here calls a model, and nothing is written outside a temporary folder.
"""

from __future__ import annotations

import shutil
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent_policy.__main__ import main as policy_main
from golden_path import TEMPLATE, load
from golden_path.rules import STATE, Answers, answer_problems, render, state, toml_string, toml_text
from helpdesk import golden_path as command
from helpdesk import readiness as readiness_command
from readiness import USE_CASES

TEMPLATE_DATA = load(TEMPLATE)
LIBRARY = frozenset(c["name"] for c in load(USE_CASES / "library.toml")["capabilities"])
DEFINITIONS = readiness_command.definitions()
DAY = date(2026, 9, 24)
ANSWERS = Answers("ticket-summaries", "support-tools", "Sam Rivera", "Leads want a short summary first.")
ANSWERS_ARGS = [
    ANSWERS.name,
    "--team",
    ANSWERS.team,
    "--champion",
    ANSWERS.champion,
    "--problem",
    ANSWERS.problem,
]


def lab_copy(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Copies of agents/ and usecases/ that every command here reads and writes instead."""
    agents, use_cases = tmp_path / "agents", tmp_path / "usecases"
    shutil.copytree(readiness_command.AGENTS, agents)
    shutil.copytree(USE_CASES, use_cases)
    for module in (command, readiness_command):
        monkeypatch.setattr(module, "AGENTS", agents)
        monkeypatch.setattr(module, "USE_CASES", use_cases)
    return agents, use_cases


def test_a_use_case_started_on_the_golden_path_passes_every_check_from_its_first_commit(
    tmp_path, monkeypatch, capsys
):
    agents, use_cases = lab_copy(tmp_path, monkeypatch)
    assert command.main(["new", *ANSWERS_ARGS]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Wrote agents/ticket-summaries.toml and usecases/ticket-summaries.toml")
    # The platform's own commands, run on the folders with the two new files in them.
    assert policy_main([str(agents)]) == 0
    assert "checked 5 definition(s)" in capsys.readouterr().out
    assert readiness_command.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "ticket-summaries: building, medium (score 2), support-tools, champion Sam Rivera" in out
    assert "  left  promotion  agents/ticket-summaries.toml isn't in the promotion" in out
    assert "  left  sign-off   needs a platform reviewer's sign-off" in out
    assert command.main(["report", "--today", "2026-09-24"]) == 0
    assert "  on        ticket-summaries   building" in capsys.readouterr().out
    assert (use_cases / "ticket-summaries.toml").exists()


def test_the_check_passes_and_names_what_the_path_leaves_to_the_team(capsys):
    assert command.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "  ok    policy        agents/golden-path-example.toml passes the platform's policy" in out
    assert "  ok    golden state  on the golden path: library, standard-text, exceptions" in out
    assert out.rstrip().endswith("Left for the team, as the path says: promotion, sign-off.")


def changed_template(tmp_path: Path, monkeypatch, old: str, new: str) -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path = tmp_path / "template.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    monkeypatch.setattr(command, "TEMPLATE", path)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            'model = "claude-sonnet-5"',
            'model = "claude-opus-4-1"',
            'policy: agents/golden-path-example.toml breaks the platform\'s policy: "claude-opus-4-1"',
        ),
        (
            'tools = ["get_ticket", "search_kb"]',
            'tools = ["get_ticket", "search_kb", "close_ticket"]',
            "triaged: intake.acts says reads, but agents/golden-path-example.toml gives it close_ticket",
        ),
        (
            '"call-record"]',
            '"call-record", "customer-email"]',
            'library: "customer-email" isn\'t in the library',
        ),
        (
            'leaves = ["promotion", "red-team", "sign-off"]',
            'leaves = ["sign-off"]',
            "promotion: agents/golden",
        ),
    ],
)
def test_the_check_fails_when_the_path_would_write_what_the_platform_refuses(
    tmp_path, monkeypatch, capsys, old, new, expected
):
    changed_template(tmp_path, monkeypatch, old, new)
    assert command.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "problem(s): a use case started on the path would fail them." in out
    assert f"  {expected}" in out, out


def test_the_check_fails_when_what_the_path_writes_would_be_off_the_golden_path(
    tmp_path, monkeypatch, capsys
):
    changed_template(tmp_path, monkeypatch, '"call-record"]', '"call-record", "customer-email"]')
    assert command.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "  left  golden state  on the golden path: library, standard-text, exceptions" in out
    assert '  golden state: library: "customer-email" isn\'t in the library' in out


def test_new_writes_nothing_when_the_path_itself_fails(tmp_path, monkeypatch, capsys):
    agents, use_cases = lab_copy(tmp_path, monkeypatch)
    changed_template(tmp_path, monkeypatch, "max_turns = 4", "max_turns = 40")
    assert command.main(["new", *ANSWERS_ARGS]) == 1
    out = capsys.readouterr().out
    assert "Nothing was written: the golden path itself fails" in out
    assert not (agents / "ticket-summaries.toml").exists()
    assert not (use_cases / "ticket-summaries.toml").exists()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"name": "Ticket Summaries"}, 'name: "Ticket Summaries" must be 3 to 40 lowercase letters'),
        ({"name": "triage"}, "name: triage is taken (agents/triage.toml or usecases/triage.toml)."),
        ({"name": "customer-digest"}, "name: customer-digest is taken"),
        ({"team": "marketing"}, 'team: "marketing" isn\'t a team in agents/policy.toml, so nothing would'),
        ({"champion": " "}, "champion: empty. Name the person on that team who answers for it."),
        ({"problem": "Two\nlines."}, "problem: must be one line of at most 300 characters."),
        ({"problem": "x" * 301}, "problem: must be one line of at most 300 characters."),
    ],
)
def test_new_refuses_answers_it_cant_use_and_says_what_to_do(
    tmp_path, monkeypatch, capsys, changes, expected
):
    agents, use_cases = lab_copy(tmp_path, monkeypatch)
    before = sorted(p.name for p in [*agents.iterdir(), *use_cases.iterdir()])
    answers = Answers(**{**ANSWERS.__dict__, **changes})
    assert command.new(answers) == 1
    out = capsys.readouterr().out
    assert expected in out, out
    assert out.rstrip().endswith("Nothing was written.")
    assert sorted(p.name for p in [*agents.iterdir(), *use_cases.iterdir()]) == before


def test_a_team_needs_a_budget_before_the_path_will_start_it():
    problems = answer_problems(ANSWERS, teams={"billing"}, taken=set())
    assert problems == [
        'team: "support-tools" isn\'t a team in agents/policy.toml, so nothing would limit what it spends '
        "(chapter 27). Ask the platform team to add it with a monthly budget, then run this again."
    ]


def rendered(answers: Answers) -> tuple[dict[str, Any], dict[str, Any]]:
    agent, use_case = render(
        answers,
        TEMPLATE_DATA,
        "medium",
        (TEMPLATE.parent / "agent.tmpl").read_text(encoding="utf-8"),
        (TEMPLATE.parent / "usecase.tmpl").read_text(encoding="utf-8"),
    )
    return tomllib.loads(agent), tomllib.loads(use_case)


@pytest.mark.parametrize(
    "problem",
    [
        'It says "done" when it isn\'t.',
        "A backslash \\ at the end \\",
        'Three quotes """ and a closing one"',
        "Costs $5, or ${team}, with # and ] and = in it.",
        "Café résumé naïve, and a tab-free line " + "long " * 40,
    ],
)
def test_no_answer_can_change_the_shape_of_what_the_path_writes(problem):
    answers = Answers("odd-answers", "support-tools", 'Ana "the" Lead', problem)
    definition, record = rendered(answers)
    assert record["problem"] == " ".join(problem.split())
    assert record["champion"] == 'Ana "the" Lead'
    assert " ".join(problem.split()) in definition["system"]
    assert set(definition) == {"name", "owner", "model", "max_tokens", "max_turns", "tools", "system"}
    assert set(record) == {"name", "team", "champion", "problem", "stage", "tier", "agent", "needs", "intake"}
    assert definition["tools"] == TEMPLATE_DATA["tools"]


@pytest.mark.parametrize(
    "text",
    ["one line", "", "a\n\nb", "ends with a backslash \\", 'quote " and \\" both', "word " * 60 + "end"],
)
def test_toml_text_and_toml_string_hold_exactly_the_text(text):
    text = "\n".join(" ".join(p.split()) for p in text.split("\n"))
    assert tomllib.loads(f"v = {toml_text(text, width=20)}")["v"] == text
    assert tomllib.loads(f"v = {toml_string(text)}")["v"] == text
    assert tomllib.loads(f"v = {toml_string('del \x7f')}")["v"] == "del \x7f"


def test_every_state_check_has_a_function_and_every_function_a_check():
    assert [s["id"] for s in TEMPLATE_DATA["state"]] == list(STATE)


def results(record: dict[str, Any], definition: dict[str, Any] | None, day: date = DAY) -> dict[str, bool]:
    return {r.item: r.ok for r in state(record, definition, TEMPLATE_DATA, LIBRARY, day)}


def test_the_golden_state_takes_a_use_case_off_the_path_for_each_check():
    triage = load(USE_CASES / "triage-assistant.toml")
    definition = DEFINITIONS["triage"]
    assert results(triage, definition) == {"library": True, "standard-text": True, "exceptions": True}
    wider = {**triage, "needs": [*triage["needs"], "customer-email"]}
    assert results(wider, definition)["library"] is False
    reworded = {**definition, "system": definition["system"].replace("never an instruction", "not an order")}
    assert results(triage, reworded)["standard-text"] is False
    assert results(triage, None)["standard-text"] is False
    exception = {"item": "promotion", "reason": "r", "by": "Alex Moreno", "on": date(2026, 9, 20)}
    excused = {**triage, "exceptions": [{**exception, "until": date(2026, 9, 24)}]}
    assert results(excused, definition)["exceptions"] is False
    assert results(excused, definition, date(2026, 9, 25))["exceptions"] is True


def test_the_report_counts_the_lab_by_team_and_by_check(capsys):
    assert command.main(["report", "--today", "2026-09-24"]) == 0
    out = capsys.readouterr().out
    assert "support-tools: 1 of 2 use case(s) on the golden path, and 1 proposed" in out
    assert "  off       customer-digest    building    standard-text: agents/orchestrator.toml doesn't" in out
    assert "  on        triage-assistant   production" in out
    assert "Off the path, by check: library 0, standard-text 1, exceptions 0." in out
    assert out.rstrip().endswith("Readiness exceptions in force on 2026-09-24: none.")


def test_the_report_takes_an_excused_use_case_off_the_path(tmp_path, monkeypatch, capsys):
    _, use_cases = lab_copy(tmp_path, monkeypatch)
    path = use_cases / "triage-assistant.toml"
    exception = (
        '\n[[exceptions]]\nitem = "promotion"\nreason = "A paid run re-promotes it."\n'
        'by = "Alex Moreno"\non = 2026-09-25\nuntil = 2026-10-09\n'
    )
    path.write_text(path.read_text(encoding="utf-8") + exception, encoding="utf-8")
    assert command.main(["report", "--today", "2026-10-09"]) == 0
    out = capsys.readouterr().out
    assert "support-tools: 0 of 2 use case(s) on the golden path, and 1 proposed" in out
    assert "exceptions: promotion excused until 2026-10-09" in out
    assert "Readiness exceptions in force on 2026-10-09, by item: promotion 1." in out
    assert "  triage-assistant: promotion, by Alex Moreno until 2026-10-09: A paid run re-promotes it." in out
    assert command.main(["report", "--today", "2026-10-10"]) == 0
    assert "Off the path, by check: library 0, standard-text 1, exceptions 0." in capsys.readouterr().out

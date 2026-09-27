"""Each import contract catches a real violation, and its failure message carries the fix.

Every test runs import-linter on a copy of the package, so the real source is never touched.
The clean copy is the control: if it failed too, the violation tests would prove nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = PYTHON_ROOT / "src" / "helpdesk"
PYPROJECT = PYTHON_ROOT / "pyproject.toml"
# lint-imports draws boxes when its output can take them, and PYTHONIOENCODING, which some shells
# set, decides what it writes. So the test says which encoding lint-imports writes and reads it
# back in the same one, whatever the shell has set.
ENCODING = "utf-8"


def lint_imports() -> str:
    exe = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    assert exe, "lint-imports was not found next to this Python; install the dev extras"
    return exe


def copy_package(workdir: Path) -> Path:
    shutil.copytree(PACKAGE, workdir / "src" / "helpdesk", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(PYPROJECT, workdir / "pyproject.toml")
    return workdir


def run_guardrail(workdir: Path) -> tuple[int, str]:
    env = {**os.environ, "PYTHONPATH": str(workdir / "src"), "PYTHONIOENCODING": ENCODING}
    result = subprocess.run(
        [lint_imports(), "--config", str(workdir / "pyproject.toml")],
        cwd=workdir,
        env=env,
        capture_output=True,
        encoding=ENCODING,
    )
    # import-linter wraps long lines; collapse whitespace so assertions can match whole sentences.
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def plant(workdir: Path, module: str, line: str) -> None:
    path = workdir / "src" / Path(*module.split(".")).with_suffix(".py")
    path.write_text(path.read_text(encoding="utf-8") + f"\n{line}  # noqa: E402,F401\n", encoding="utf-8")


def test_clean_copy_keeps_every_contract(tmp_path):
    code, output = run_guardrail(copy_package(tmp_path))
    assert code == 0, output
    assert "7 kept, 0 broken" in output


def test_data_layer_importing_a_service_is_caught(tmp_path):
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.data.repository", "from helpdesk.services import tickets")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.data.repository -> helpdesk.services.tickets" in output
    assert "the data layer must not know about services, routes or the assistant" in output


def test_model_importing_a_service_is_caught(tmp_path):
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.model.mock", "from helpdesk.services import tickets")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.model.mock -> helpdesk.services.tickets" in output
    assert "Pass what the model needs in as arguments instead" in output


def test_route_importing_the_data_layer_is_caught_with_the_fix(tmp_path):
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.api.routes", "from helpdesk.data import repository")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "BROKEN" in output
    assert "helpdesk.api.routes -> helpdesk.data.repository" in output
    assert "move the query into helpdesk.services and call that from the route" in output


def test_the_assistant_importing_the_data_layer_is_caught_with_the_fix(tmp_path):
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.assistant.tools", "from helpdesk.data import repository")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.assistant.tools -> helpdesk.data.repository" in output
    assert "call that from the route or the tool" in output


def test_routes_and_the_assistant_must_not_import_each_other(tmp_path):
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.api.routes", "from helpdesk.assistant import agent")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.api.routes -> helpdesk.assistant.agent" in output
    assert "put what both need in helpdesk.services" in output


def test_model_importing_the_assistant_is_caught(tmp_path):
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.model.types", "from helpdesk.assistant import tools")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.model.types -> helpdesk.assistant.tools" in output


def test_a_service_importing_the_sdk_is_caught_with_the_fix(tmp_path):
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.services.tickets", "import anthropic")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.services.tickets -> anthropic" in output
    assert "Take a ModelClient as an argument instead, so tests can pass the mock" in output


def test_a_module_written_after_the_contract_is_covered_too(tmp_path):
    # The protected contract lists who may import the SDK, not who may not, so a new module is
    # covered without anyone adding it, even when its import is inside a function.
    workdir = copy_package(tmp_path)
    (workdir / "src" / "helpdesk" / "reports.py").write_text(
        "def summary() -> str:\n    import anthropic\n\n    return str(anthropic)\n", encoding="utf-8"
    )
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.reports -> anthropic" in output


def test_a_service_importing_the_mcp_sdk_is_caught_with_the_fix(tmp_path):
    # The MCP server is one more way in to the tools (chapter 12). A rule written against the SDK,
    # in a service, would hold for that way in and no other.
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.services.tickets", "from mcp.shared.exceptions import MCPError")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.services.tickets -> mcp " in output
    assert "Put the rule in helpdesk.services or the toolbox, where every way in applies it" in output


def test_a_way_out_reached_through_the_labs_own_imports_is_caught_with_the_fix(tmp_path):
    # Chapter 20. The fitness test reads only the assistant's, the services' and the data layer's own
    # imports, so each of these passed it and the other six contracts: the data layer importing the
    # MCP client (which starts programs and opens URLs), the assistant importing the Anthropic
    # client module (which imports the SDK), and a service importing http, which no module imported
    # before, so it wasn't in the graph until now.
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.data.repository", "from helpdesk import mcp_client")
    plant(workdir, "helpdesk.assistant.agent", "from helpdesk.model import anthropic_client")
    plant(workdir, "helpdesk.services.tickets", "import http.client")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "6 kept, 1 broken" in output
    assert "helpdesk.data is not allowed to import subprocess" in output
    assert "helpdesk.data.repository -> helpdesk.mcp_client (l." in output
    assert "helpdesk.mcp_client -> subprocess (l." in output
    assert "helpdesk.assistant is not allowed to import anthropic" in output
    assert "helpdesk.assistant.agent -> helpdesk.model.anthropic_client (l." in output
    assert "helpdesk.model.anthropic_client -> anthropic (l." in output
    assert "helpdesk.services.tickets -> http (l." in output
    assert "Put the call behind a composition root, such as helpdesk.mcp_server, and give" in output


def test_a_tool_that_imports_the_code_that_decides_is_caught_with_the_fix(tmp_path):
    # Chapter 19: an agent proposes and a person decides. If a tool could import the decisions, a
    # model could approve its own proposal by calling that tool.
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.assistant.proposing", "from helpdesk.services import decisions")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.assistant.proposing -> helpdesk.services.decisions" in output
    assert "An agent's tool files a proposal with helpdesk.services.proposals instead" in output


def test_the_mcp_server_and_the_routes_cannot_decide_either(tmp_path):
    workdir = copy_package(tmp_path)
    plant(workdir, "helpdesk.mcp_server", "from helpdesk.services import decisions")
    plant(workdir, "helpdesk.api.routes", "from helpdesk.services import decisions")
    code, output = run_guardrail(workdir)
    assert code != 0, output
    assert "helpdesk.mcp_server -> helpdesk.services.decisions" in output
    assert "helpdesk.api.routes -> helpdesk.services.decisions" in output

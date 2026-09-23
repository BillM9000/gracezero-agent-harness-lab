"""The layer guardrail catches a real violation, and its failure message carries the fix.

Both tests run import-linter on a copy of the package, so the real source is never touched.
The clean copy is the control: if it failed too, the violation test would prove nothing.
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
    assert "3 kept, 0 broken" in output


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

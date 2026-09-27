"""The test run's own settings, in pyproject.toml (chapter 10): an expected failure that passes fails
the run, so an xfail mark can't hide a bug that's been fixed, or let a test that no longer fails
stand as a done item's proof."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

PLANTED = """
import pytest


@pytest.mark.xfail(reason="the bug this marks was fixed")
def test_marked_as_failing_but_passes():
    assert True
"""


def test_an_expected_failure_that_passes_fails_the_run(tmp_path):
    planted = tmp_path / "test_planted.py"
    planted.write_text(PLANTED, encoding="utf-8")
    run = subprocess.run(
        # --rootdir keeps pytest inside tmp_path. Without it, the root is the common folder of the
        # settings file and the planted test, and collection lists folders other programs may be
        # deleting at that moment, which failed the run now and then on a busy machine.
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-c", str(PYPROJECT), "--rootdir", str(tmp_path), str(planted),
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1, run.stdout
    assert "[XPASS(strict)] the bug this marks was fixed" in run.stdout

"""The test run's own settings, in pyproject.toml (chapter 10): an expected failure that passes fails
the run, so an xfail mark can't hide a bug that's been fixed, or let a test that no longer fails
stand as a done item's proof."""

from __future__ import annotations

import shutil
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
    # The lab's settings, copied next to the planted test, so every folder pytest lists is inside
    # tmp_path. Given the lab's own file, pytest collects each folder above the planted test that
    # isn't above the settings file: on Windows, C:\Users down to the shared temporary folder, where
    # other programs delete folders as it lists them, which failed the run now and then with
    # FileNotFoundError (--rootdir alone didn't stop it). The copy is the lab's file byte for byte,
    # so the run still judges the lab's own settings.
    settings = tmp_path / "pyproject.toml"
    shutil.copyfile(PYPROJECT, settings)
    assert settings.read_bytes() == PYPROJECT.read_bytes()
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            str(settings),
            "--rootdir",
            str(tmp_path),
            str(planted),
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1, run.stdout
    assert "[XPASS(strict)] the bug this marks was fixed" in run.stdout

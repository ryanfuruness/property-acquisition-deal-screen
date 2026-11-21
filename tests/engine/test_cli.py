"""The ``python -m engine`` command line."""

import json
import subprocess
import sys

from engine_test_helpers import REPO_ROOT

FIXTURE = "tests/engine/fixtures/jvc_60_units.json"


def run(*args):
    return subprocess.run([sys.executable, "-m", "engine", *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, check=True).stdout


def test_summary():
    out = run(FIXTURE)
    for text in ("NOI", "DSCR Year 1", "Walk-away price", "Sensitivity", "OM yield check", "Mandate fit"):
        assert text in out


def test_json_output():
    data = json.loads(run(FIXTURE, "--json"))
    assert data["underwriting"]["metrics"]["unit_count"]["value"] == 60
    assert data["mandate_fit"]["verdict"] in ("Pursue", "Needs work", "Pass")

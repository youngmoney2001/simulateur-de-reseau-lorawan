"""Les trois numéros de version (paquet Python, module, interface web) doivent concorder."""

import json
import re
from pathlib import Path

import lsim

ROOT = Path(__file__).resolve().parents[2]


def test_versions_match():
    pyproject = (ROOT / "python" / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    web = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["version"]
    assert declared == lsim.__version__ == web


def test_changelog_mentions_current_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {lsim.__version__} " in text

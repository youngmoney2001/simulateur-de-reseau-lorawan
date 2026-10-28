"""Rapports PDF et Excel : contenu, neutralisation des formules, CLI."""

from pathlib import Path

import pytest

from lsim.__main__ import main
from lsim.export import RunResult, run_scenario
from lsim.report import _safe_text, write_pdf, write_xlsx
from lsim.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def run() -> RunResult:
    return run_scenario(load_scenario(ROOT / "examples" / "quartier_sf9.yaml"))


def test_safe_text_neutralises_formulas():
    assert _safe_text("=HYPERLINK('x')") == "'=HYPERLINK('x')"
    assert _safe_text("+1") == "'+1"
    assert _safe_text("-2") == "'-2"
    assert _safe_text("@SUM") == "'@SUM"
    assert _safe_text("Quartier") == "Quartier"


def test_xlsx_has_summary_and_one_row_per_device(tmp_path, run):
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "r.xlsx"
    write_xlsx(run, out)
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Synthèse", "Dispositifs"]
    assert wb["Dispositifs"].max_row == len(run.rows) + 1
    values = {row[0].value: row[1].value for row in wb["Synthèse"].iter_rows(min_row=2)}
    assert values["Émises"] == run.totals.sent
    assert values["Reçues"] == run.totals.received


def test_pdf_is_written(tmp_path, run):
    pytest.importorskip("reportlab")
    out = tmp_path / "r.pdf"
    write_pdf(run, out)
    assert out.read_bytes().startswith(b"%PDF")


def test_cli_rejects_unknown_format(tmp_path, capsys):
    rc = main(["report", str(ROOT / "examples" / "quartier_sf9.yaml"), "-o", str(tmp_path / "r.txt")])
    assert rc == 2
    assert "pdf" in capsys.readouterr().err

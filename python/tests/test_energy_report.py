"""Choix du profil énergie : calcul par dispositif, rapports et CLI."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from lsim.__main__ import main
from lsim.energy_report import DEFAULT_ENERGY_PROFILE, ENERGY_PROFILES, device_energies, profile_name
from lsim.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "quartier_sf9.yaml"


def _dev(sf=7, payload=10, dbm=14.0, period_s=600.0):
    return SimpleNamespace(spreading_factor=sf, payload_bytes=payload, tx_power_dbm=dbm,
                           period_ns=int(period_s * 1e9))


def test_profiles_and_default():
    assert list(ENERGY_PROFILES) == ["rak4631", "sx1262-stm32l072"]
    assert DEFAULT_ENERGY_PROFILE == "rak4631"
    assert profile_name("sx1262-stm32l072").startswith("SX1262")
    with pytest.raises(ValueError):
        profile_name("stm32")


def test_choice_changes_the_result():
    devices = [_dev()]
    rak = device_energies(devices, "rak4631")[0].energy_per_message_j
    sx = device_energies(devices, "sx1262-stm32l072")[0].energy_per_message_j
    assert rak is not None and sx is not None
    assert rak != pytest.approx(sx)


def test_energy_grows_with_spreading_factor():
    e7, e12 = (device_energies([_dev(sf=s)])[0].energy_per_message_j for s in (7, 12))
    assert e12 > 10 * e7


def test_period_too_short_gives_none():
    e = device_energies([_dev(sf=12, period_s=0.001)])[0]
    assert e.energy_per_message_j is None and e.average_current_ua is None


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError):
        device_energies([_dev()], "inconnu")


def test_scenario_devices_all_get_energy():
    scenario = load_scenario(EXAMPLE)
    devices, _g, _i = scenario.deploy()
    out = device_energies(devices, "sx1262-stm32l072")
    assert len(out) == len(devices)
    assert all(e.energy_per_message_j is not None and e.average_current_ua > 0 for e in out)


def test_cli_rejects_unknown_profile(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["report", str(EXAMPLE), "-o", str(tmp_path / "r.xlsx"),
              "--energy-profile", "inconnu"])
    assert exc.value.code == 2
    assert "energy-profile" in capsys.readouterr().err


def test_xlsx_report_uses_chosen_profile(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "r.xlsx"
    assert main(["report", str(EXAMPLE), "-o", str(out),
                 "--energy-profile", "sx1262-stm32l072"]) == 0
    wb = openpyxl.load_workbook(out)
    header = [c.value for c in wb["Dispositifs"][1]]
    assert "Énergie par message (mJ)" in header and "Courant moyen (µA)" in header
    summary = {r[0]: r[1] for r in wb["Synthèse"].iter_rows(min_row=2, values_only=True)}
    assert summary["Profil énergie (classe A, un message par période)"].startswith("SX1262")


def test_pdf_report_with_energy(tmp_path):
    pytest.importorskip("reportlab")
    out = tmp_path / "r.pdf"
    assert main(["report", str(EXAMPLE), "-o", str(out)]) == 0
    assert out.read_bytes().startswith(b"%PDF")

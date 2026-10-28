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


def test_run_scenario_adds_energy_only_when_requested():
    from lsim.export import run_scenario

    scenario = load_scenario(EXAMPLE)
    plain = run_scenario(scenario)
    assert plain.energy_profile is None
    assert all(r.energy_per_message_j is None for r in plain.rows)
    with_e = run_scenario(scenario, energy_profile="sx1262-stm32l072")
    assert with_e.energy_profile == "sx1262-stm32l072"
    assert all(r.energy_per_message_j > 0 for r in with_e.rows)
    # Les compteurs de simulation ne dépendent pas du calcul énergie.
    assert with_e.totals == plain.totals


def test_parquet_has_energy_columns_only_with_profile(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    from lsim.export import run_scenario, write_parquet

    scenario = load_scenario(EXAMPLE)
    plain_path, energy_path = tmp_path / "a.parquet", tmp_path / "b.parquet"
    write_parquet(run_scenario(scenario), plain_path)
    write_parquet(run_scenario(scenario, energy_profile="rak4631"), energy_path)
    plain = pq.read_table(plain_path)
    energy = pq.read_table(energy_path)
    assert "energy_per_message_j" not in plain.column_names
    assert "energy_per_message_j" in energy.column_names
    assert energy.schema.metadata[b"lsim.energy_profile"] == b"rak4631"
    assert b"lsim.energy_profile" not in (plain.schema.metadata or {})


def test_cli_run_accepts_energy_profile(tmp_path):
    pytest.importorskip("pyarrow")
    out = tmp_path / "run.parquet"
    assert main(["run", str(EXAMPLE), "-o", str(out), "--energy-profile", "rak4631"]) == 0
    assert out.exists()
    with pytest.raises(SystemExit):
        main(["run", str(EXAMPLE), "-o", str(out), "--energy-profile", "x"])

from __future__ import annotations

import math

import pytest

from lsim.reference.loader import load_siegen_indoor


@pytest.fixture(scope="module")
def siegen() -> dict:
    return load_siegen_indoor()


def test_provenance_and_licence(siegen):
    d = siegen["dataset"]
    assert d["licence"] == "CC BY 4.0"
    assert d["article_doi"] == "10.1109/ACCESS.2025.3569164"
    assert d["dataset_doi"] == "10.5281/zenodo.15349730"
    assert len(d["code_commit"]) == 40
    assert d["code_commit"].startswith("7fa0327")


def test_ldplm_mw_values_match_notebook_output(siegen):
    p = siegen["models"]["LDPLM-MW"]["parameters"]
    assert p["PL_d0_db"] == pytest.approx(16.233661)
    assert p["n"] == pytest.approx(4.914496)
    assert p["L_c_db"] == pytest.approx(7.103567)
    assert p["L_w_db"] == pytest.approx(1.140166)


def test_model_parameters_are_finite(siegen):
    for name, model in siegen["models"].items():
        for key, value in model["parameters"].items():
            assert math.isfinite(value), f"{name}.{key}"


def test_physical_inconsistency_is_documented(siegen):
    # FSPL à 1 m, 868 MHz = 20·log10(4π·1·868e6/c) ≈ 31,2 dB : PL(d0) ajusté est très inférieur.
    fspl_1m = 20 * math.log10(4 * math.pi * 1.0 * 868e6 / 299_792_458.0)
    assert fspl_1m == pytest.approx(31.2, abs=0.1)
    assert fspl_1m - siegen["models"]["LDPLM-MW"]["parameters"]["PL_d0_db"] > 10
    assert any("espace libre" in c for c in siegen["caveats"])


def test_wall_label_ambiguity_is_documented(siegen):
    assert any("c_walls" in c and "brick" in c for c in siegen["caveats"])

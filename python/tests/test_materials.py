"""Atténuation des pavés par matériau (UIT-R P.2040-4) : natif, validation, scénario."""

import cmath
import math
import warnings

import pytest

from lsim.materials import MATERIAL_NAMES, traversal_loss
from lsim.scenario import load_scenario


def _reference_slab_loss_db(a, b, c, d, f_hz, thickness_m):
    # Implémentation indépendante de l'éq. 43b (θ = 0), en complexes Python.
    f = f_hz / 1e9
    eps = a * f**b
    sigma = c * f**d
    eps_c = complex(eps, -sigma / (2 * math.pi * f_hz * 8.8541878128e-12))
    n = cmath.sqrt(eps_c)
    r = (1 - n) / (1 + n)
    q = 2 * math.pi * thickness_m * f_hz / 299792458.0 * n
    e1 = cmath.exp(-1j * q)
    t = (1 - r * r) * e1 / (1 - r * r * e1 * e1)
    return -20 * math.log10(abs(t))


def test_concrete_1ghz_total_matches_reference_and_exceeds_material_term():
    loss, extrapolated = traversal_loss("concrete", 1e9, 0.2)
    assert loss == pytest.approx(_reference_slab_loss_db(5.24, 0, 0.0462, 0.7822, 1e9, 0.2), abs=1e-6)
    assert loss == pytest.approx(7.787, abs=0.01)
    assert loss > 1636 * 0.0462 / math.sqrt(5.24) * 0.2  # interfaces inclus
    assert not extrapolated


def test_brick_matches_reference():
    loss, _ = traversal_loss("brick", 1e9, 0.1)
    assert loss == pytest.approx(_reference_slab_loss_db(3.91, 0, 0.0238, 0.16, 1e9, 0.1), abs=1e-6)


def test_out_of_documented_range_is_flagged():
    _, extrapolated = traversal_loss("concrete", 868.1e6, 0.2)
    assert extrapolated


def test_zero_thickness_is_lossless_and_air_is_lossless():
    assert traversal_loss("concrete", 868e6, 0.0)[0] == pytest.approx(0.0, abs=1e-9)
    assert traversal_loss("air", 868e6, 1.0)[0] == 0.0


@pytest.mark.parametrize("args", [
    ("unobtainium", 868e6, 0.1),
    ("concrete", 0.0, 0.1),
    ("concrete", float("nan"), 0.1),
    ("concrete", 868e6, -0.1),
])
def test_rejects_invalid_inputs(args):
    with pytest.raises(ValueError):
        traversal_loss(*args)


def test_native_material_count_matches_python_table():
    from lsim._native import LIB
    assert LIB.lsim_material_count() == len(MATERIAL_NAMES) == 15


def _scenario(tmp_path, obstacle_line, frequency="868.1e6"):
    text = f"""
schema_version: 1
name: pavés
propagation: {{frequency_hz: {frequency}}}
groups:
  - name: g
    count: 1
    placement: {{type: disk, radius_m: 100}}
    spreading_factor: 9
    payload_bytes: 20
    tx_power_dbm: 14
    period_s: 900
    messages: 1
environment:
  obstacles:
    - {obstacle_line}
"""
    return load_scenario(text)


def test_material_obstacle_gets_computed_attenuation(tmp_path):
    sc = _scenario(tmp_path, "{x_min_m: 10, y_min_m: 0, x_max_m: 20, y_max_m: 5, height_m: 8, "
                             "material: brick, thickness_m: 0.1}", frequency="1e9")
    expected, _ = traversal_loss("brick", 1e9, 0.1)
    assert sc.environment.obstacles[0].attenuation_db == pytest.approx(expected)


def test_material_obstacle_warns_outside_documented_range(tmp_path):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _scenario(tmp_path, "{x_min_m: 10, y_min_m: 0, x_max_m: 20, y_max_m: 5, height_m: 8, "
                            "material: concrete, thickness_m: 0.2}")
    assert any("hors de la plage" in str(w.message) for w in caught)


@pytest.mark.parametrize("obstacle", [
    "{x_min_m: 1, y_min_m: 0, x_max_m: 2, y_max_m: 1, height_m: 8, material: concrete}",
    "{x_min_m: 1, y_min_m: 0, x_max_m: 2, y_max_m: 1, height_m: 8, thickness_m: 0.2}",
    "{x_min_m: 1, y_min_m: 0, x_max_m: 2, y_max_m: 1, height_m: 8, attenuation_db: 3, "
    "material: concrete, thickness_m: 0.2}",
    "{x_min_m: 1, y_min_m: 0, x_max_m: 2, y_max_m: 1, height_m: 8, material: lava, thickness_m: 0.2}",
])
def test_scenario_rejects_inconsistent_material_fields(tmp_path, obstacle):
    with pytest.raises(Exception):
        _scenario(tmp_path, obstacle)


def test_obstacle_hash_is_deterministic_without_material(tmp_path):
    # Pavé sans matériau : hash reproductible (champs optionnels retirés du hash).
    plain = _scenario(tmp_path, "{x_min_m: 1, y_min_m: 0, x_max_m: 2, y_max_m: 1, height_m: 8, "
                                "attenuation_db: 3}")
    again = _scenario(tmp_path, "{x_min_m: 1, y_min_m: 0, x_max_m: 2, y_max_m: 1, height_m: 8, "
                                "attenuation_db: 3}")
    assert plain.sha256 == again.sha256

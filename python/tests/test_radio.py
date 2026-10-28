"""Tests du bilan de liaison et de la propagation (cœur natif via ctypes)."""

import math

import pytest

from lsim import StatusError
from lsim.radio import (
    LinkBudget,
    LogDistanceModel,
    free_space_path_loss_db,
    receiver_sensitivity_dbm,
)


@pytest.mark.parametrize(
    "sf, expected",
    [(7, -123.0), (8, -126.0), (9, -129.0), (10, -132.0), (11, -134.5), (12, -137.0)],
)
def test_sensitivity_125khz_table(sf, expected):
    assert receiver_sensitivity_dbm(sf, 125_000) == pytest.approx(expected)


def test_sensitivity_decreases_with_sf():
    values = [receiver_sensitivity_dbm(sf) for sf in range(7, 13)]
    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("bw", [250_000, 500_000])
def test_uncalibrated_bandwidth_is_refused_explicitly(bw):
    with pytest.raises(StatusError) as err:
        receiver_sensitivity_dbm(7, bw)
    assert err.value.code == 7  # UncalibratedSensitivity


def test_free_space_reference_values():
    assert free_space_path_loss_db(1000.0, 868e6) == pytest.approx(91.2, abs=0.05)
    assert free_space_path_loss_db(1000.0, 2.4e9) == pytest.approx(100.05, abs=0.05)


def test_log_distance_slope_is_10n_per_decade():
    m = LogDistanceModel(exponent=3.5)
    assert m.path_loss_db(1000.0) - m.path_loss_db(100.0) == pytest.approx(35.0)


def test_log_distance_equals_free_space_for_n2():
    m = LogDistanceModel(exponent=2.0)
    assert m.path_loss_db(1234.0) == pytest.approx(free_space_path_loss_db(1234.0, m.frequency_hz))


def test_mapl_and_range_roundtrip():
    budget = LinkBudget(tx_power_dbm=14.0)
    mapl = budget.max_allowable_path_loss_db(receiver_sensitivity_dbm(12))
    assert mapl == pytest.approx(151.0)
    m = LogDistanceModel(exponent=2.7)
    d = m.range_m(mapl)
    assert m.path_loss_db(d) == pytest.approx(mapl, abs=1e-6)


def test_fade_margin_reduces_range():
    m = LogDistanceModel()
    s = receiver_sensitivity_dbm(12)
    r0 = m.range_m(LinkBudget().max_allowable_path_loss_db(s))
    r1 = m.range_m(LinkBudget(fade_margin_db=10.0).max_allowable_path_loss_db(s))
    assert r1 < r0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_rejects_non_finite_inputs(bad):
    with pytest.raises(ValueError):
        free_space_path_loss_db(bad, 868e6)
    with pytest.raises(ValueError):
        LinkBudget(tx_power_dbm=bad)


def test_rejects_invalid_model_parameters():
    with pytest.raises(ValueError):
        LogDistanceModel(exponent=0.5)
    with pytest.raises(ValueError):
        LogDistanceModel().path_loss_db(0.0)
    with pytest.raises(ValueError):
        receiver_sensitivity_dbm(6)

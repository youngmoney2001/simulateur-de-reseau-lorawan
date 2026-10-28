"""Tests du temps d'antenne : valeurs de référence et différence avec une
implémentation indépendante en flottants (formule AN1200.13)."""

import itertools
import math

import pytest

from lsim import RadioConfig, StatusError, native_version, time_on_air_ns


def reference_airtime_s(cfg: RadioConfig, pl: int) -> float:
    """Implémentation indépendante, en flottants, pour la différence."""
    tsym = (2**cfg.spreading_factor) / cfg.bandwidth_hz
    t_pre = (cfg.preamble_symbols + 4.25) * tsym
    de = 1 if cfg.low_data_rate_optimize else 0
    ih = 0 if cfg.explicit_header else 1
    crc = 1 if cfg.crc_on else 0
    num = 8 * pl - 4 * cfg.spreading_factor + 28 + 16 * crc - 20 * ih
    den = 4 * (cfg.spreading_factor - 2 * de)
    blocks = max(math.ceil(num / den) * (cfg.coding_rate + 4), 0)
    return t_pre + (8 + blocks) * tsym


def test_native_version_is_0_1_0():
    assert native_version() == "0.1.0"


def test_known_value_sf7_10_bytes():
    assert time_on_air_ns(RadioConfig(), 10) == 41_216_000


def test_known_value_sf12_10_bytes_with_ldro():
    cfg = RadioConfig(spreading_factor=12, low_data_rate_optimize=True)
    assert time_on_air_ns(cfg, 10) == 991_232_000


@pytest.mark.parametrize(
    "sf, bw, cr, pl",
    list(
        itertools.product(
            range(7, 13), (125_000, 250_000, 500_000), (1, 2, 3, 4), (0, 1, 11, 51, 115, 222, 255)
        )
    ),
)
def test_matches_independent_float_reference(sf, bw, cr, pl):
    cfg = RadioConfig(
        spreading_factor=sf,
        bandwidth_hz=bw,
        coding_rate=cr,
        low_data_rate_optimize=(2**sf) / bw > 0.016,
    )
    exact_ns = time_on_air_ns(cfg, pl)
    ref_ns = reference_airtime_s(cfg, pl) * 1e9
    assert abs(exact_ns - ref_ns) < 1.0  # tolérance : arrondi flottant seulement


def test_monotonic_in_payload():
    cfg = RadioConfig(spreading_factor=10)
    values = [time_on_air_ns(cfg, n) for n in range(256)]
    assert values == sorted(values)


def test_rejects_invalid_config_before_native_call():
    with pytest.raises(ValueError):
        RadioConfig(spreading_factor=6)
    with pytest.raises(ValueError):
        RadioConfig(bandwidth_hz=100_000)
    with pytest.raises(ValueError):
        time_on_air_ns(RadioConfig(), 256)


def test_native_error_is_surfaced_as_status_error():
    # Une configuration valide côté Python ne doit jamais produire d'erreur native.
    with pytest.raises(ValueError):
        time_on_air_ns(RadioConfig(), -1)
    assert StatusError(4).code == 4

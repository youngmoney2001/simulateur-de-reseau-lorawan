"""Shadowing log-normal par dispositif : validation, reproductibilité, effet et scénario."""

import pytest

from lsim.scenario import PropagationModel
from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks

# Anneau de dispositifs autour de la limite de sensibilité SF9 (~16 km avec n = 2,7).
# Émissions décalées de 2 s (pas de collision) : seul le budget de liaison varie.
DEVICES = [EndDevice(x_m=15000.0 + 13.0 * i, spreading_factor=9,
                     start_offset_ns=2_000_000_000 * i) for i in range(150)]


def test_zero_sigma_equals_default():
    base = simulate_uplinks(DEVICES, Gateway(), Propagation())
    zero = simulate_uplinks(DEVICES, Gateway(), Propagation(shadowing_sigma_db=0.0, shadowing_seed=5))
    assert base == zero


def test_shadowing_is_reproducible_and_seed_dependent():
    p1 = Propagation(shadowing_sigma_db=8.0, shadowing_seed=1)
    p2 = Propagation(shadowing_sigma_db=8.0, shadowing_seed=2)
    a = simulate_uplinks(DEVICES, Gateway(), p1)
    assert a == simulate_uplinks(DEVICES, Gateway(), p1)
    assert a != simulate_uplinks(DEVICES, Gateway(), p2)


def test_shadowing_changes_reception_near_edge():
    base = simulate_uplinks(DEVICES, Gateway(), Propagation())
    shadowed = simulate_uplinks(DEVICES, Gateway(),
                                Propagation(shadowing_sigma_db=8.0, shadowing_seed=1))
    # Sans shadowing, l'anneau est sous la sensibilité ; le shadowing ouvre des liaisons.
    assert base.totals.received == 0
    assert shadowed.totals.received > 0


@pytest.mark.parametrize("sigma", [-0.1, 30.5, float("nan"), float("inf")])
def test_invalid_sigma_rejected(sigma):
    with pytest.raises(ValueError):
        Propagation(shadowing_sigma_db=sigma)


def test_invalid_seed_rejected():
    with pytest.raises(ValueError):
        Propagation(shadowing_seed=-1)
    with pytest.raises(ValueError):
        Propagation(shadowing_seed=2**64)


def test_scenario_schema_accepts_shadowing_and_rejects_bad_values():
    ok = PropagationModel(shadowing_sigma_db=6.0)
    assert ok.shadowing_seed is None
    with pytest.raises(ValueError):
        PropagationModel(shadowing_sigma_db=31.0)
    with pytest.raises(ValueError):
        PropagationModel(shadowing_sigma_db=-1.0)

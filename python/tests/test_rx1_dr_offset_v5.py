"""RX1DROffset de bout en bout : enveloppe v5, du ctypes jusqu'au moteur (I5-c).

L'enveloppe v5 imbrique v4, qui imbrique v3. Elle porte un RX1DROffset par dispositif, que le
moteur applique au **DR courant** du terminal, suivi par l'ADR :

    RX1_DR = clamp(DR courant − offset, 0, max_dr)   puis   SF = dr_sf[RX1_DR]

Sans ADR le DR courant est inconnu : le SF ne bouge jamais et la table de radios, déjà calculée
avec l'offset, fait foi. Les tests ci-dessous activent donc l'ADR.

Un seul dispositif par exécution : avec deux, la descente du second est repliée en RX2 dès que la
première occupe la passerelle, et RX2 porte son propre SF régional — l'offset y est sans effet.
"""

from __future__ import annotations

S = 1_000_000_000

import pytest

from lsim.closed_loop import LoopOptions
from lsim.closed_loop_v3 import LoopRegion, simulate_closed_loop_v3
from lsim.lora import StatusError
from lsim.environment import Environment, Obstacle
from lsim.simulator import EndDevice, Gateway, Propagation
from lsim.trace_events import DeviceRadio

def _region():
    """EU868 : dr_sf[i] = 12 − i, max_dr = 5. Un dispositif SF7 est donc DR5, et l'offset a toute
    la table pour descendre."""
    return LoopRegion(dr_sf=(12, 11, 10, 9, 8, 7) + (0,) * 10, max_dr=5, max_tx_power_index=7,
                      power_step_tenth_db=20)


def _contexte():
    """Un dispositif SF7 (DR5), ADR active, une descente par émission."""
    device = EndDevice(x_m=80.0, spreading_factor=7, start_offset_ns=0, period_ns=60 * S,
                       messages=1)
    radio = DeviceRadio(freq_hz=868_100_000, dr=5, rx1_hz=868_100_000, rx1_sf=7,
                        rx1_bw_hz=125_000)
    options = LoopOptions(adr=True, downlink_every=1)
    return ([device], [radio], [_region()], options)


def _run(offsets):
    devices, radios, regions, options = _contexte()
    return simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, options,
                                   rx1_dr_offset=offsets)


# --- L'offset est effectif ---------------------------------------------------------------------


def test_offset_is_effective_from_python_to_the_engine():
    """T-V5-2 Python : l'offset 3 descend le dispositif de DR5 (SF7) à DR2 (SF10).

    Chaque pas de SF double l'airtime, soit un facteur ~8 sur trois pas. Contrôle positif
    obligatoire (dixième garde-fou) : sans offset la descente a bien lieu et dure le temps du
    SF7. Un moteur qui ignorerait l'offset échouerait la dernière assertion.
    """
    sans = _run((0,))
    avec = _run((3,))

    assert len(sans.downlinks) == 1, "contrôle positif : une descente RX1 a bien eu lieu"
    assert len(avec.downlinks) == 1
    air_sans = sans.downlinks[0].air_ns
    air_avec = avec.downlinks[0].air_ns
    assert air_sans > 0
    assert air_avec > 5 * air_sans, f"SF10 attendu : {air_avec} ns contre {air_sans} ns au SF7"


def test_airtime_is_monotone_over_the_whole_table():
    """T-V5-9 : chaque pas d'offset monte d'un SF, donc allonge la descente.

    Le balayage interdit un décrochage partiel, par exemple un moteur qui n'appliquerait
    l'offset qu'à partir d'un certain rang.
    """
    previous = 0
    for offset in range(6):
        out = _run((offset,))
        assert len(out.downlinks) == 1
        air = out.downlinks[0].air_ns
        assert air > previous, f"offset {offset} : {air} ns n'allonge pas {previous} ns"
        previous = air


# --- Non-régression ----------------------------------------------------------------------------


def test_null_offsets_give_the_v3_results():
    """T-V5-1 : sans offsets, les résultats sont ceux de v3 — l'enveloppe n'est pas régressive."""
    devices, radios, regions, options = _contexte()
    v3 = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, options)
    devices, radios, regions, options = _contexte()
    v5 = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, options,
                                 rx1_dr_offset=(0,))

    assert len(v3.downlinks) == len(v5.downlinks) == 1
    assert v3.downlinks[0].air_ns == v5.downlinks[0].air_ns
    assert v3.downlinks[0].delivered == v5.downlinks[0].delivered
    assert v3.totals == v5.totals
    assert v3.uplinks == v5.uplinks


# --- Refus explicites --------------------------------------------------------------------------


def test_offset_beyond_the_regional_max_is_refused():
    """T-V5-4 : au-delà de `max_dr` le moteur refuse, avec contrôle positif sur la borne."""
    admis = _run((5,))  # max_dr = 5 : accepté
    assert len(admis.downlinks) == 1

    with pytest.raises(StatusError):
        _run((6,))


@pytest.mark.parametrize("mauvais", [(0, 0), (), (0, 0, 0)])
def test_offset_count_must_match_the_device_count(mauvais):
    """Une entrée par dispositif, ou None. Tout autre compte est refusé avant tout appel natif."""
    if len(mauvais) == 0:
        return  # vide = entrée nulle, admis
    devices, radios, regions, options = _contexte()
    with pytest.raises(ValueError):
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, options,
                                rx1_dr_offset=mauvais)


@pytest.mark.parametrize("mauvais", [(-1,), (True,), (1.5,)])
def test_offsets_must_be_positive_integers(mauvais):
    devices, radios, regions, options = _contexte()
    with pytest.raises(ValueError):
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, options,
                                rx1_dr_offset=mauvais)


# --- Environnement ----------------------------------------------------------------------------


def test_environment_reaches_the_engine():
    """Le relief et les obstacles atteignent le moteur.

    Le champ `env` de la structure v3 existait mais valait toujours None, si bien que l'environnement
    était perdu. Contrôle positif : sans obstacle les trames sont reçues, avec un mur elles ne le
    sont plus — les deux exécutions ne diffèrent que par `environment`.
    """
    device = EndDevice(x_m=400.0, spreading_factor=7, period_ns=60 * S, messages=4)
    radio = DeviceRadio(freq_hz=868_100_000, dr=5, rx1_hz=868_100_000, rx1_sf=7)
    region = _region()
    options = LoopOptions(adr=True, downlink_every=1)
    mur = Obstacle(200.0, -500.0, 220.0, 500.0, 60.0, 80.0)

    plat = simulate_closed_loop_v3([device], Gateway(), Propagation(), [radio], [region], options)
    muraille = simulate_closed_loop_v3([device], Gateway(), Propagation(), [radio], [region],
                                       options, environment=Environment(obstacles=(mur,)))

    assert plat.totals.received == 4, "contrôle positif : sans obstacle, tout est reçu"
    assert muraille.totals.received == 0
    assert all(u.rssi_dbm > r.rssi_dbm for u, r in zip(plat.uplinks, muraille.uplinks))

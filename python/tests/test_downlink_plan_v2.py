"""Jalon I0 : enveloppe ABI versionnée du planificateur (`lsim_plan_downlinks_v2`).

Le repli RX2 est **opt-in** et n'est pas implémenté en I0 : les événements et l'occupation
produits par `plan_native_v2` doivent donc être **identiques** à ceux de `plan_native`, que les
paramètres RX2 soient absents ou renseignés. Seules les entrées invalides sont refusées.
"""

import ctypes
import random

import pytest

from lsim.downlink_plan import (LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION, PLAN_STATUS_BASE, DeviceRx2,
                                _CPlanDeviceRx2, _CPlanDownlinksV2Args, plan_native,
                                plan_native_v2)
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import simulate_uplinks_trace
from lsim.trace_events import ProtocolOptions, device_radios


def _scenario(seed):
    rng = random.Random(seed)
    raw = {
        "schema_version": 1, "name": "i0", "seed": rng.randrange(1000),
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
        "groups": [{
            "name": "g0", "count": rng.randint(2, 8),
            "placement": {"type": "disk", "radius_m": 900},
            "spreading_factor": 7, "payload_bytes": 20, "tx_power_dbm": 14.0,
            "period_s": 60, "messages": 8, "start_spread_s": 60,
        }],
    }
    return Scenario(ScenarioModel.model_validate(raw))


def _jeu(seed=11):
    scenario = _scenario(seed)
    options = ProtocolOptions(confirmed_uplinks=True, downlink_every=2,
                              downlink_payload_bytes=40, gateway_tx_power_dbm=27.0)
    devices, _g, _i = scenario.deploy()
    radios = device_radios(scenario)
    result = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                    scenario.environment, gateway_busy=())
    return result.records, radios, options


def test_v2_sans_rx2_egale_v1():
    """`rx2` absent : l'enveloppe v2 reproduit la v1 exactement."""
    records, radios, options = _jeu()
    assert plan_native_v2(records, radios, options) == plan_native(records, radios, options)


@pytest.mark.parametrize("seed", range(20))
def test_v2_sans_rx2_egale_v1_sur_scenarios_aleatoires(seed):
    records, radios, options = _jeu(seed)
    assert plan_native_v2(records, radios, options) == plan_native(records, radios, options)


def test_v2_avec_rx2_renseigne_ne_cree_aucun_repli():
    """Le repli RX2 est opt-in et non implémenté en I0 : résultats encore identiques."""
    records, radios, options = _jeu()
    rx2 = tuple(DeviceRx2(rx2_hz=869_525_000, rx2_sf=12, rx2_bw_hz=125_000) for _ in radios)
    attendu = plan_native(records, radios, options)
    obtenu = plan_native_v2(records, radios, options, rx2)
    assert obtenu == attendu
    # Contrôle positif : le scénario produit bien des descentes, le test n'est pas vide.
    assert any(e.kind != "uplink" for e in attendu[0])
    assert attendu[1], "aucune occupation passerelle : scénario inadapté"


def test_v2_accepte_les_valeurs_absentes():
    records, radios, options = _jeu()
    attendu = plan_native(records, radios, options)
    # SF nul (aucun repli), fréquence nulle (non renseignée), largeur nulle (reprend rx1_bw_hz).
    for rx2 in (
        tuple(DeviceRx2() for _ in radios),
        tuple(DeviceRx2(rx2_sf=12) for _ in radios),
        tuple(DeviceRx2(rx2_hz=869_525_000) for _ in radios),
        tuple(DeviceRx2(rx2_bw_hz=500_000) for _ in radios),
    ):
        assert plan_native_v2(records, radios, options, rx2) == attendu


@pytest.mark.parametrize("mauvais", [
    DeviceRx2(rx2_sf=6),            # SF hors 7..12
    DeviceRx2(rx2_sf=13),
    DeviceRx2(rx2_sf=12, rx2_bw_hz=100_000),  # largeur hors {125k, 250k, 500k}
    DeviceRx2(rx2_sf=12, rx2_hz=-1),          # fréquence négative
])
def test_v2_refuse_un_rx2_invalide(mauvais):
    records, radios, options = _jeu()
    rx2 = [DeviceRx2() for _ in radios]
    rx2[0] = mauvais
    with pytest.raises(ValueError, match=str(PLAN_STATUS_BASE + 2)):
        plan_native_v2(records, radios, options, tuple(rx2))


@pytest.mark.parametrize("decalage", [-1, +1])
def test_v2_refuse_un_comptage_incoherent(decalage):
    """`rx2_count` protège la lecture : un comptage annoncé différent est refusé.

    Sans ce champ, le cœur lirait `device_count` entrées quelle que soit la taille réelle du
    tableau — une lecture hors bornes silencieuse.
    """
    records, radios, options = _jeu()
    rx2 = tuple(DeviceRx2() for _ in range(len(radios) + decalage))
    with pytest.raises(ValueError, match=str(PLAN_STATUS_BASE + 1)):
        plan_native_v2(records, radios, options, rx2)


def test_la_version_abi_est_exposee_et_egale_a_un():
    # Toute modification de cette constante est une rupture d'ABI : elle doit être explicite.
    assert LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION == 1


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8,
                    reason="dispositions épinglées pour le LP64 exécuté par le harnais ABI")
def test_disposition_ctypes_conforme_au_harnais_abi():
    """Le pont ctypes doit reproduire exactement la disposition C épinglée par `abi_layout.cpp`.

    Sans ce contrôle, un champ oublié côté Python décale silencieusement toute la structure :
    les valeurs lues par le cœur ne sont plus celles écrites par l'appelant.
    """
    assert ctypes.sizeof(_CPlanDeviceRx2) == 32
    assert _CPlanDeviceRx2.rx2_hz.offset == 0
    assert _CPlanDeviceRx2.rx2_sf.offset == 8
    assert _CPlanDeviceRx2.rx2_bw_hz.offset == 12
    assert _CPlanDeviceRx2.reserved.offset == 16

    assert ctypes.sizeof(_CPlanDownlinksV2Args) == 128
    assert _CPlanDownlinksV2Args.struct_size.offset == 0
    assert _CPlanDownlinksV2Args.abi_version.offset == 4
    assert _CPlanDownlinksV2Args.uplinks.offset == 8
    assert _CPlanDownlinksV2Args.uplink_count.offset == 16
    assert _CPlanDownlinksV2Args.devices.offset == 24
    assert _CPlanDownlinksV2Args.device_count.offset == 32
    assert _CPlanDownlinksV2Args.options.offset == 40
    assert _CPlanDownlinksV2Args.rx2.offset == 48
    assert _CPlanDownlinksV2Args.events.offset == 56
    assert _CPlanDownlinksV2Args.event_capacity.offset == 64
    assert _CPlanDownlinksV2Args.event_count.offset == 72
    assert _CPlanDownlinksV2Args.busy.offset == 80
    assert _CPlanDownlinksV2Args.busy_capacity.offset == 88
    assert _CPlanDownlinksV2Args.busy_count.offset == 96
    assert _CPlanDownlinksV2Args.rx2_count.offset == 104
    assert _CPlanDownlinksV2Args.reserved.offset == 112

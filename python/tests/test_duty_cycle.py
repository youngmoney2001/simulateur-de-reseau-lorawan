"""Rapport cyclique par dispositif : décalage des émissions, validation, scénario."""

import pytest

from lsim.scenario import GroupModel
from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks


def test_duty_cycle_delays_next_frames():
    dev = EndDevice(x_m=10.0, messages=3, period_ns=100_000_000, duty_cycle=0.1)
    res = simulate_uplinks([dev], Gateway(), Propagation())
    a = res.per_device[0].airtime_ns // 3
    assert res.gateway.observation_ns == 21 * a


def test_default_duty_cycle_is_unlimited():
    dev = EndDevice(x_m=10.0, messages=3, period_ns=100_000_000)
    res = simulate_uplinks([dev], Gateway(), Propagation())
    a = res.per_device[0].airtime_ns // 3
    assert res.gateway.observation_ns == 200_000_000 + a


@pytest.mark.parametrize("value", [0.0, -0.1, 1.01, float("nan")])
def test_invalid_duty_cycle_rejected(value):
    with pytest.raises(ValueError):
        EndDevice(duty_cycle=value)


def test_scenario_group_duty_cycle_validated():
    assert GroupModel.model_fields["duty_cycle"].default == 1.0
    with pytest.raises(ValueError):
        GroupModel(name="g", count=1, placement={"type": "disk", "radius_m": 10},
                   duty_cycle=0.0)


# --- Limites publiées dans le résumé de run --------------------------------------------------

def _scenario(*groupes):
    from lsim.scenario import Scenario, ScenarioModel, GatewayModel
    return Scenario(ScenarioModel(schema_version=1, name="limites", seed=1,
                                  gateways=[GatewayModel(name="gw", x_m=0, y_m=0)],
                                  groups=list(groupes)))


def _groupe(**kwargs):
    from lsim.scenario import DiskPlacement
    base = dict(name="g", count=1, placement=DiskPlacement(type="disk", radius_m=100),
                spreading_factor=7, payload_bytes=10, tx_power_dbm=14, period_s=60, messages=1)
    base.update(kwargs)
    return GroupModel(**base)


def test_limite_eu868_depend_de_la_frequence():
    """Une même région, deux fréquences, deux limites : sous-bandes M (1 %) puis N (0,1 %)."""
    from lsim.api_server import _duty_cycle_out
    m = _duty_cycle_out(_scenario(_groupe(region="EU868", channel_freq_hz=868_100_000)))[0]
    n = _duty_cycle_out(_scenario(_groupe(region="EU868", channel_freq_hz=869_525_000)))[0]
    assert m["limit"] == 0.01
    assert n["limit"] == 0.001


def test_limite_publiee_avec_sa_source():
    from lsim.api_server import _duty_cycle_out
    d = _duty_cycle_out(_scenario(_groupe(region="EU868")))[0]
    # La source est obligatoire dans le modèle régional : sans elle, la limite ne vaut rien.
    assert "ETSI EN 300 220-2" in d["source"]
    assert d["region"] == "EU868"
    assert d["channel_freq_hz"] == 868_100_000
    assert d["eirp_dbm"] == 14.0


def test_region_sans_sous_bande_publie_une_limite_absente():
    """US915, AU915, AS923, KR920, IN865 n'ont aucune sous-bande : pas de limite, pas 100 %."""
    from lsim.api_server import _duty_cycle_out
    d = _duty_cycle_out(_scenario(_groupe(region="US915", channel_freq_hz=903_900_000,
                                          tx_power_dbm=20.0)))[0]
    # La clé est absente, pas nulle : c'est la convention de l'API (`exclude_none`), la même
    # que `lost_mesh` hors mesh. L'absence de clé est donc le signe « aucune limite » — et
    # surtout pas « 100 % », qui serait une invention.
    assert "limit" not in d
    # La ligne existe quand même : elle dit que le plan ne borne pas, ce qui est une information.
    assert d["region"] == "US915"


def test_sans_region_le_champ_est_absent():
    from lsim.api_server import _duty_cycle_out
    assert _duty_cycle_out(_scenario(_groupe())) is None


def test_groupes_sans_region_ne_sont_pas_publies():
    """Un mélange ne publie que les groupes dont on connaît le plan : rien n'est deviné."""
    from lsim.api_server import _duty_cycle_out
    rows = _duty_cycle_out(_scenario(_groupe(name="sans"), _groupe(name="avec", region="EU868")))
    assert [r["group"] for r in rows] == ["avec"]


def test_resume_de_run_publie_limites_et_reste_valide():
    """Le champ est accepté par le contrat : un résumé qui ne valide pas ne sortirait jamais."""
    from lsim.api_contract import RunSummary
    from lsim.api_server import _duty_cycle_out, _summary_out
    from lsim.simulator import NetworkCounters, GatewayRxCounters
    sc = _scenario(_groupe(region="EU868"))
    body = _summary_out("runrunrun1", sc,
                        NetworkCounters(sent=1, received=1, duplicates=0, lost_sensitivity=0,
                                        lost_collision=0, lost_gateway_busy=0, airtime_ns=1),
                        GatewayRxCounters(received=1, lost_sensitivity=0, lost_collision=0,
                                          lost_gateway_busy=0, observation_ns=1),
                        None, None)
    resume = RunSummary.model_validate(body)
    assert resume.duty_cycle[0].limit == 0.01

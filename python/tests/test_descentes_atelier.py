"""Descentes réseau dans l'atelier : réglage par capteur, compilation, latence publiée.

Le chemin complet est exercé une fois, bout en bout : on pose un capteur de classe C qui
attend une commande, on compile la session, on lance le run, et on lit l'attente. Ce n'est pas
un test de la compilation seule — c'est la preuve que le réglage posé dans l'atelier arrive
jusqu'au moteur et que le chiffre revient.
"""

import time

import pytest

from lsim import api_server as srv
from lsim.api_contract import DeviceClassList, RunSummary
from lsim.study_compile import compile_session
from lsim.study_contract import Node, SensorSettings, DownlinkSettings
from lsim.study_cli import GatewayConfig
from test_api_server import _wait_done
from test_study_api import _make_api, _session

NODES = [
    {"id": "gw1", "kind": "border", "name": "Frontière", "x_m": 0, "y_m": 0},
    {"id": "c-a", "kind": "sensor", "name": "Capteur A", "x_m": 100, "y_m": 0},
    {"id": "c-c", "kind": "sensor", "name": "Capteur C", "x_m": 100, "y_m": 0},
]


def _capteur(nid, **kw) -> Node:
    return Node(id=nid, kind="sensor", name=nid, x_m=100.0, y_m=0.0,
                sensor=SensorSettings(**kw))


def _groupes(nodes) -> dict:
    conf = {n.id: GatewayConfig() for n in nodes if n.kind in ("border", "relay")}
    return {g["name"]: g
            for g in compile_session(nodes, conf, 7).body["scenario"]["groups"]}


# --- Le réglage ne s'écrit que s'il quitte le défaut ---------------------------------------------

def test_a_chantier_written_before_keeps_its_group_byte_for_byte():
    """« A » sans descente : le groupe compilé est exactement celui d'avant.

    C'est ce qui garde son empreinte à un chantier écrit avant l'existence de ces réglages —
    et donc ses chiffres, puisque le moteur ne fait alors rien de plus.
    """
    gw = Node(id="gw1", kind="border", name="gw1", x_m=0.0, y_m=0.0)
    avant = _groupes([gw, _capteur("c1")])["c1"]
    apres = _groupes([gw, _capteur("c1", device_class="A", downlink=None)])["c1"]
    assert avant == apres
    assert "device_class" not in avant
    assert "downlink" not in avant


def test_the_setting_is_written_as_soon_as_it_leaves_the_default():
    gw = Node(id="gw1", kind="border", name="gw1", x_m=0.0, y_m=0.0)
    groupe = _groupes([gw, _capteur("c1", device_class="C",
                                    downlink=DownlinkSettings(count=1,
                                                              first_request_s=10))])["c1"]
    assert groupe["device_class"] == "C"
    assert groupe["downlink"]["first_request_s"] == 10
    # L'écart n'a pas d'objet pour une commande unique : il n'est pas écrit.
    assert "request_period_s" not in groupe["downlink"]


def test_several_commands_carry_their_spacing():
    gw = Node(id="gw1", kind="border", name="gw1", x_m=0.0, y_m=0.0)
    groupe = _groupes([gw, _capteur("c1", device_class="B",
                                    downlink=DownlinkSettings(count=3, first_request_s=10,
                                                              request_period_s=30,
                                                              periodicity=7))])["c1"]
    assert groupe["downlink"] == {"count": 3, "first_request_s": 10.0, "periodicity": 7,
                                  "clock_drift_ppm": 0, "request_period_s": 30.0}


# --- Le catalogue de classes vient du moteur -----------------------------------------------------

@pytest.fixture()
def api(tmp_path):
    with _make_api(tmp_path) as a:
        yield a


def test_device_classes_come_from_the_engine_with_their_slots(api):
    status, body = api.call("GET", "/api/v1/device-classes")
    assert status == 200, body
    DeviceClassList.model_validate(body)
    classes = {c["name"]: c for c in body["classes"]}
    assert set(classes) == {"A", "B", "C"}
    # Les intervalles entre créneaux sont calculés par le moteur, pas recopiés : la période de
    # balise est de 128 s, et une périodicité k ouvre 2**(7-k) créneaux par période.
    slots = {p["value"]: p for p in classes["B"]["periodicites"]}
    assert slots[0]["intervalle_s"] == pytest.approx(1.0)
    assert slots[7]["intervalle_s"] == pytest.approx(128.0)
    assert slots[0]["slots_par_periode"] == 128
    assert slots[7]["slots_par_periode"] == 1
    # Ce que la classe ne change pas est servi avec : c'est le garde-fou contre un sélecteur
    # qu'on croirait général.
    for c in body["classes"]:
        assert "ACK" in c["ne_change_pas"]


# --- Bout en bout : du réglage posé dans l'atelier à l'attente mesurée --------------------------

def test_the_latency_measured_is_the_one_the_class_decides(api):
    """Deux capteurs identiques, deux classes, la même commande à t = 10 s."""
    sid = _session(api, NODES)
    for nid, classe in (("c-a", "A"), ("c-c", "C")):
        status, body = api.call(
            "POST", f"/api/v1/sessions/{sid}/nodes/{nid}/sensor",
            {"period_s": 60, "messages": 3, "device_class": classe,
             "downlink": {"count": 1, "first_request_s": 10}})
        assert status == 200, body
        # Le réglage revient tel qu'il a été posé : l'interface n'a rien à réinventer.
        relu = next(n for n in body["nodes"] if n["id"] == nid)
        assert relu["sensor"]["device_class"] == classe
        assert relu["sensor"]["downlink"]["first_request_s"] == 10
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 7})
    assert status == 202, body
    run_id = body["run_id"]
    _wait_done(api, run_id)
    _, summary = api.call("GET", f"/api/v1/runs/{run_id}/summary")
    RunSummary.model_validate(summary)
    d = summary["downlink"]
    assert d is not None and (d["requested"], d["delivered"]) == (2, 2)

    _, page = api.call("GET", f"/api/v1/runs/{run_id}/devices")
    par_groupe = {r["group"]: r for r in page["items"]}
    # Mesuré : 0 s en classe C, 51 s en classe A (prochain uplink à 60 s, puis RX1).
    assert par_groupe["c-c"]["downlink_latency_s"] == pytest.approx(0.0, abs=1e-6)
    assert 50.0 < par_groupe["c-a"]["downlink_latency_s"] < 52.0
    assert par_groupe["c-a"]["downlink_delivered"] == 1


def test_a_session_without_requests_publishes_no_summary(api):
    """Rien n'est publié : un objet de zéros se lirait comme « aucune commande arrivée »."""
    sid = _session(api, [NODES[0], NODES[1]])
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 7})
    assert status == 202, body
    _wait_done(api, body["run_id"])
    _, summary = api.call("GET", f"/api/v1/runs/{body['run_id']}/summary")
    assert "downlink" not in summary or summary["downlink"] is None
    _, page = api.call("GET", f"/api/v1/runs/{body['run_id']}/devices")
    for r in page["items"]:
        assert r.get("downlink_latency_s") is None

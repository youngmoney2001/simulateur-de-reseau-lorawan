"""Descentes à l'initiative du réseau : le seul réglage que la classe d'écoute détermine.

Un ACK, une réponse MAC ou une charge `downlink_every` sont déclenchés par un uplink : ils
tombent donc toujours dans RX1 ou RX2, et la classe n'y change rien — c'est §3 bis de
`docs/MAC_CONSOLIDATION.md`. Une demande née au moment choisi par le réseau, elle, attend
une fenêtre, et c'est la classe qui dit laquelle.

Les chiffres de ce fichier sont mesurés, pas supposés. Scénario : un terminal à 100 m d'une
passerelle par défaut, 3 messages espacés de 60 s, une seule demande à t = 10 s.
"""

import pytest
import yaml

from lsim.export import run_scenario
from lsim.scenario import Scenario, load_scenario

BASE = """
schema_version: 1
name: descentes
seed: 7
gateway:
  x_m: 0
  y_m: 0
groups:
  - name: g
    count: 1
    placement: {type: explicit, positions: [[100, 0]]}
    spreading_factor: 7
    period_s: 60
    messages: 3
"""


def _scenario(groupe: str = "") -> Scenario:
    return load_scenario(BASE + groupe)


def _run(groupe: str, **downlink):
    bloc = "    downlink:\n" + "".join(
        f"      {k}: {v}\n" for k, v in downlink.items()) if downlink else ""
    return run_scenario(_scenario(groupe + "\n" + bloc))


def test_a_group_without_requests_keeps_its_fingerprint():
    """La clé quitte le hachage quand elle est vide : un scénario écrit avant ne bouge pas."""
    from lsim.scenario import Scenario
    sans = _scenario().sha256
    vide = _scenario("    downlink: null\n").sha256
    assert sans == vide
    # Dès qu'une demande existe, l'empreinte change : deux scénarios différents ne se
    # confondent pas sous prétexte que l'un est « presque » l'autre.
    avec = _scenario("    downlink: {count: 1, first_request_s: 10}\n").sha256
    assert avec != sans


def test_the_request_reaches_every_device_of_the_group():
    devices = _scenario(
        "    device_class: B\n"
        "    downlink: {count: 2, first_request_s: 10, request_period_s: 30, periodicity: 3}\n"
    ).deploy()[0]
    assert devices[0].downlink is not None
    d = devices[0].downlink
    assert int(d.device_class) == 1          # B
    assert (d.count, d.first_request_ns, d.request_period_ns) == (2, 10_000_000_000,
                                                                  30_000_000_000)
    assert (d.periodicity, d.clock_drift_ppm) == (3, 0)


def test_validation_of_the_request_block():
    with pytest.raises(Exception):
        _scenario("    downlink: {count: 2, first_request_s: 10}\n")      # période manquante
    with pytest.raises(Exception):
        _scenario("    downlink: {count: 1, periodicity: 8}\n")
    with pytest.raises(Exception):
        _scenario("    downlink: {count: 1, clock_drift_ppm: 1001}\n")


# --- La latence, par classe -------------------------------------------------------------------

def test_class_c_is_immediate_and_class_a_waits_for_the_next_uplink():
    """Mesuré : 0 s en classe C, 51 s en classe A.

    Le terminal émet à 0, 60 et 120 s. Une demande née à 10 s attend donc le prochain
    uplink (60 s) puis RX1, une seconde après la fin de l'émission : 51 s d'attente.
    """
    c = _run("    device_class: C\n", count=1, first_request_s=10).downlink
    assert c is not None and (c.requested, c.delivered) == (1, 1)
    assert c.latency_mean_s == pytest.approx(0.0, abs=1e-6)

    a = _run("    device_class: A\n", count=1, first_request_s=10).downlink
    assert a is not None and (a.requested, a.delivered) == (1, 1)
    assert 50.0 < a.latency_mean_s < 52.0


def test_class_b_waits_for_its_ping_slot_and_the_periodicity_decides_how_long():
    """Mesuré : 0,94 s en périodicité 0, 64,3 s en périodicité 7.

    La périodicité n'est pas un détail : elle place la classe B **de part et d'autre** de la
    classe A. À 7 (un slot par période de 128 s), attendre le ping slot coûte plus cher que
    d'attendre le prochain uplink — 64 s contre 51 s. Le dire vaut mieux que laisser croire
    que « classe B » est, par nature, plus rapide que « classe A ».
    """
    rapide = _run("    device_class: B\n", count=1, first_request_s=10, periodicity=0).downlink
    lent = _run("    device_class: B\n", count=1, first_request_s=10, periodicity=7).downlink
    a = _run("    device_class: A\n", count=1, first_request_s=10).downlink
    assert rapide is not None and lent is not None and a is not None
    assert rapide.delivered == 1 and lent.delivered == 1
    # Un slot toutes les 0,96 s : l'attente est inférieure à la seconde.
    assert rapide.latency_mean_s < 1.0
    # Un slot par période de 128 s : l'attente dépasse celle de la classe A.
    assert lent.latency_mean_s > a.latency_mean_s


def test_no_request_means_no_counter_and_no_summary():
    """Sans demande, le résumé est absent — pas un zéro qui dirait « aucune livrée »."""
    r = run_scenario(_scenario())
    assert r.downlink is None
    assert r.rows[0].downlink_delivered is None
    assert r.rows[0].downlink_latency_s is None


def test_several_requests_are_counted_and_the_mean_is_a_mean():
    r = _run("    device_class: C\n", count=3, first_request_s=10, request_period_s=20)
    assert r.downlink is not None
    assert (r.downlink.requested, r.downlink.delivered) == (3, 3)
    assert r.downlink.latency_mean_s == pytest.approx(0.0, abs=1e-6)
    assert r.downlink.latency_max_s == pytest.approx(0.0, abs=1e-6)


# --- Ce que le second passage de l'API suppose -------------------------------------------------

def test_mac_payload_does_not_move_transmission_starts():
    """Mesure dont dépend la latence publiée par l'API.

    Le résumé de descente est calculé par un second passage natif, sans la charge MAC ni
    l'ADR du run. C'est exact à une nuance près : RX1 s'ouvre après la **fin** de
    l'émission, donc une trame allongée décale la latence d'au plus la durée ajoutée.

    Ce que ce test garde, c'est que tout le reste est immobile : les instants de **début**
    d'émission sont les mêmes avec et sans charge MAC réservée. Mesuré ici avec 10 octets
    ajoutés aux rangs 2, 4 et 6 à SF7 : les durées passent de 41,2 ms à 56,6 ms, et les
    débuts ne bougent pas d'une nanoseconde. L'écart induit sur la latence est donc de
    l'ordre de 15 ms, à comparer aux 51 s que la classe A attend.
    """
    from lsim.simulator import (EndDevice, Gateway, Propagation, simulate_uplinks_trace)

    devices = [EndDevice(0.0, 100.0, spreading_factor=7, period_ns=60 * 10**9, messages=6)]
    args = (devices, Gateway(0.0, 0.0), Propagation())
    reserv = [(0, r, 10) for r in (2, 4, 6)]

    sans = simulate_uplinks_trace(*args, None)
    avec = simulate_uplinks_trace(*args, None, reservations=reserv)

    durees_sans = [r.end_ns - r.start_ns for r in sans.records]
    durees_avec = [r.end_ns - r.start_ns for r in avec.records]
    assert durees_avec != durees_sans                       # la charge allonge les trames
    assert [r.start_ns for r in avec.records] == [r.start_ns for r in sans.records]


def test_the_published_example_keeps_its_numbers():
    """`docs/exemples/descentes_reseau.yaml` : trois classes, une demande, trois attentes.

    Le test garde l'exemple, pas l'inverse : si un chiffre bouge, c'est le fichier ou le
    moteur qui a changé, et il faut regarder pourquoi avant de corriger l'attente.
    """
    from pathlib import Path

    from lsim.scenario import load_scenario

    racine = Path(__file__).resolve().parents[2]
    run = run_scenario(load_scenario(racine / "docs" / "exemples" / "descentes_reseau.yaml"))
    par_groupe = {r.group: r.downlink_latency_s for r in run.rows}
    assert set(par_groupe) == {"classe-a", "classe-b", "classe-c"}
    assert run.downlink is not None and run.downlink.requested == 3
    assert run.downlink.delivered == 3
    # C : immédiat. A : prochain uplink + RX1. B : slot de ping, entre les deux.
    assert par_groupe["classe-c"] == pytest.approx(0.0, abs=1e-6)
    assert 50.0 < par_groupe["classe-a"] < 52.0
    assert 0.0 < par_groupe["classe-b"] < par_groupe["classe-a"]

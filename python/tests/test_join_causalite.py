"""Causalité du jeu de tentatives de jointure (directive D3.13, §1).

Le Join-Accept partage l'émetteur de la passerelle avec les ACK et les autres descentes. On ne
sait donc **qu'après** l'avoir placé si une tentative aboutit. Une prédiction faite avant le
placement partagé ne peut pas servir à décider des tentatives suivantes : le jeu de tentatives
doit se déduire de ce qui a été **observé**.

Le scénario exigé par la directive est joué ici dans son entier :

| Étape | Attendu | Test |
|---|---|---|
| (i) un terminal envoie un Join-Request | tentative présente, requête reçue | `test_scenario_complet_de_causalite` |
| (ii) la prévision aurait annoncé une réussite | sans concurrence, une seule tentative | `test_sans_concurrence_une_seule_tentative` |
| (iii) un ACK concurrent occupe l'émetteur | RX1 et RX2 refusées (`gateway_busy`) | `test_scenario_complet_de_causalite` |
| (iv) le Join-Accept manque RX1 et RX2 | aucun Join-Accept émis, session 0 | `test_scenario_complet_de_causalite` |
| (v) la tentative suivante a lieu | 2e tentative à 20 s, session ouverte | `test_scenario_complet_de_causalite` |

Et les quatre propriétés opposables :

| Propriété | Test |
|---|---|
| Aucune tentative nécessaire supprimée prématurément | `test_aucune_tentative_necessaire_supprimee` |
| Aucune tentative émise après une jointure réussie | `test_aucune_tentative_apres_jointure_reussie` |
| Jamais de session ouverte sur une prévision | `test_aucune_session_sur_une_prevision` |
| Compteurs conformes aux transmissions réelles | `test_compteurs_conformes_aux_transmissions` |
"""

import yaml

from lsim.scenario import load_scenario
from lsim.trace_events import ProtocolOptions, build_trace

EXEMPLE = "docs/exemples/retransmissions_ack_tardif.yaml"


def _lent(data):
    """Trames de 51 octets en SF12 : une transmission couvre plus d'une seconde."""
    data["groups"][0].update({"spreading_factor": 12, "payload_bytes": 51, "period_s": 60,
                              "messages": 3, "start_spread_s": 4})


def _trace(modifier=None, **reglages):
    data = yaml.safe_load(open(EXEMPLE, encoding="utf-8"))
    if modifier is not None:
        modifier(data)
    data["retransmissions"].update({"ack_delay_ms": 0, "join_requests_s": [10],
                                    "join_retries": 2, "retries": 2, **reglages})
    return build_trace(load_scenario(yaml.safe_dump(data)), ProtocolOptions())


def _concurrence(data):
    """Trois copies d'ACK : elles couvrent RX1 **et** RX2 de la première tentative."""
    _lent(data)


CONCURRENCE = {"ack_repetitions": 3, "ack_delay_ms": 12000}


# --- scénario exigé -----------------------------------------------------------------------------

def test_sans_concurrence_une_seule_tentative():
    """(ii) Sans ACK concurrent, la première tentative aboutit : la seconde n'a pas lieu."""
    joins = _trace().retransmissions.joins
    assert [(j.device, round(j.request_ns / 1e9, 1)) for j in joins] == [(0, 10.0)]
    assert joins[0].accept_outcome == "delivered" and joins[0].session == 1


def test_scenario_complet_de_causalite():
    """(i)-(v) Un ACK occupe RX1 et RX2 ; la tentative suivante doit avoir lieu."""
    joins = _trace(_concurrence, **CONCURRENCE).retransmissions.joins

    # (i) deux tentatives réellement jouées, à 10 s et à 20 s.
    assert [(j.device, round(j.request_ns / 1e9, 1)) for j in joins] == [(0, 10.0), (0, 20.0)]
    assert [j.request_outcome for j in joins] == ["received", "received"]

    # (iii)-(iv) la première tentative rate ses deux fenêtres : l'émetteur est occupé.
    premiere = joins[0]
    assert [(e.window, e.outcome, e.emitted) for e in premiere.accepts] == [
        ("rx1", "gateway_busy", False), ("rx2", "gateway_busy", False)]

    # (v) la seconde tentative aboutit et ouvre la session.
    seconde = joins[1]
    assert [(e.window, e.outcome, e.emitted) for e in seconde.accepts] == [
        ("rx1", "delivered", True)]
    assert seconde.session == 1


def test_aucune_tentative_necessaire_supprimee():
    """La tentative rendue nécessaire par un échec n'est pas supprimée par la prévision."""
    resultat = _trace(_concurrence, **CONCURRENCE).retransmissions
    assert len(resultat.joins) == 2
    assert sum(1 for j in resultat.joins if j.joined) == 1
    # La session ne s'ouvre qu'après le Join-Accept effectivement délivré, à 26,5 s, pas à 10 s.
    assert resultat.joins[0].accept_ns is None or resultat.joins[0].session == 0
    assert resultat.joins[1].session == 1


def test_aucune_tentative_apres_jointure_reussie():
    """Une tentative postérieure à une jointure obtenue n'est ni jouée ni émise."""
    resultat = _trace().retransmissions
    assert len(resultat.joins) == 1
    # Un seul Join-Accept émis : celui de la tentative qui a abouti, aucune émission redondante.
    assert resultat.join_accepts_emitted == 1
    evenements = [(e.kind, e.outcome) for e in _trace().events if e.kind.startswith("join")]
    assert evenements == [("join_request", "received"), ("join_accept", "delivered")]


def test_aucune_session_sur_une_prevision():
    """La session s'ouvre sur un Join-Accept reçu, jamais sur une prévision de réussite."""
    resultat = _trace(_concurrence, **CONCURRENCE).retransmissions
    # La première tentative aurait réussi sans concurrence ; elle n'ouvre rien ici.
    assert resultat.joins[0].session == 0
    assert resultat.joins[0].accept_outcome == "gateway_busy"
    # Une seule session ouverte pour le terminal (indice 1), malgré deux tentatives : aucune
    # session n'a été ouverte par la tentative qui a échoué.
    assert max(a.session for a in resultat.attempts) == 1
    assert resultat.joins[1].accept_ns is not None
    # Aucune trame antérieure au Join-Accept délivré n'est rattachée à la session 1.
    assert all(a.session == 0 for a in resultat.attempts
               if a.end_ns is not None and a.end_ns < resultat.joins[1].accept_ns)
    # Les trames émises avant le Join-Accept ne sont pas rattachées à une session.
    rattachees = [a.session for a in resultat.attempts]
    assert rattachees[0] == 0 and 1 in rattachees


def test_compteurs_conformes_aux_transmissions():
    """`join_accepts_emitted` ne compte que les Join-Accept réellement émis."""
    avec_echec = _trace(_concurrence, **CONCURRENCE).retransmissions
    # Deux fenêtres refusées + une délivrée : une seule émission réelle.
    assert sum(1 for j in avec_echec.joins for e in j.accepts) == 3
    assert avec_echec.join_accepts_emitted == 1

    sans_echec = _trace().retransmissions
    assert sans_echec.join_accepts_emitted == 1

    # Aucun Join-Accept émis, aucune session : les compteurs restent cohérents.
    perdu = _trace(_concurrence, **dict(CONCURRENCE, ack_repetitions=3,
                                        join_retries=1)).retransmissions
    assert perdu.join_accepts_emitted == 0
    assert sum(1 for j in perdu.joins if j.joined) == 0

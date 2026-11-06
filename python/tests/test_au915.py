"""Plan AU915-928 (RP002) : canaux, débits, RX1, file, et parcours complet de données.

Lot I6-b1. Les assertions de ce fichier encodaient autrefois le défaut du mappage RX1
(table US915 transplantée) et des limites de charge utile ; elles ont été remplacées par
les valeurs conformes. Voir `docs/I6_B1_REGIONS.md`.

Distinction de grandeurs, à ne pas confondre :
- **M** : taille maximale du MACPayload ;
- **N** : charge applicative maximale **sans FOpts**, N = M − 8 — c'est N que stocke
  `max_frm_payload` et que compare `queue_payload_max` ;
- **Join-Accept** : un PHYPayload complet (17 ou 33 octets), qui n'emprunte pas la file.
"""

import re

import pytest

from lsim.au915 import AU915
from lsim.join import JOIN_ACCEPT_BYTES, RX1, accept_airtime_ns
from lsim.plan import get_plan, plan_names
from lsim.trace_events import _radio
from lsim.us915 import US915
from test_uplink import DEV, Env, open_dl, up

# RX1 à RX1DROffset 0 : RP002-1.0.5 §3.8.7. DR0→DR8 … DR6→DR13.
RX1_ATTENDU = {0: 8, 1: 9, 2: 10, 3: 11, 4: 12, 5: 13, 6: 13}

# Table N complète, RP002-1.0.5 table 44 (colonnes compatibles répéteurs), N = M − 8.
# DR8 : M = 61  → N = 53.   DR9 : M = 137 → N = 129.
N_ATTENDU = {0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222, 6: 222,
             8: 53, 9: 129, 10: 222, 11: 222, 12: 222, 13: 222}


def _sf_bw(datr):
    """`(SF, bande en Hz)` d'un débit « SF12BW500 »."""
    m = re.match(r"^SF(\d+)BW(\d+)$", datr)
    return int(m.group(1)), int(m.group(2)) * 1000


def test_registry_has_au915():
    assert "AU915" in plan_names()
    assert get_plan("AU915") is AU915


@pytest.mark.parametrize("freq,index", [(915.2, 0), (927.8, 63), (915.9, 64), (927.1, 71)])
def test_au_channel_frequencies(freq, index):
    assert AU915.channel_index(freq) == index


def test_au_channel_outside_plan_refused():
    with pytest.raises(ValueError):
        AU915.channel_index(927.9)


@pytest.mark.parametrize("datr,dr", [
    ("SF12BW125", 0), ("SF11BW125", 1), ("SF10BW125", 2), ("SF9BW125", 3),
    ("SF8BW125", 4), ("SF7BW125", 5), ("SF8BW500", 6),
])
def test_au_uplink_data_rates(datr, dr):
    assert AU915.data_rate_index(datr) == dr


def test_au_dr13_is_not_an_uplink_rate():
    with pytest.raises(ValueError):
        AU915.data_rate_index("SF7BW500")


# ---------------------------------------------------------------------------
# T-B1-1 — mappage RX1 à offset 0
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tx_dr,rx1_datr", [
    (0, "SF12BW500"), (1, "SF11BW500"), (2, "SF10BW500"), (3, "SF9BW500"),
    (4, "SF8BW500"), (5, "SF7BW500"), (6, "SF7BW500"),
])
def test_au_rx1_data_rate_offset_zero(tx_dr, rx1_datr):
    """RP002-1.0.5 §3.8.7. Remplace sept assertions erronées (table US915)."""
    assert AU915.rx1(tx_dr, 0)[1] == rx1_datr


# ---------------------------------------------------------------------------
# T-B1-2 — invariant physique : le SF est conservé, transporté sur 500 kHz
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tx_dr", [0, 1, 2, 3, 4, 5])
def test_au_rx1_preserves_spreading_factor(tx_dr):
    """À offset 0, la descente garde le SF de la montante (DR0→DR8 … DR5→DR13).

    DR6 est exclu : SF8/500 monte vers DR13 (SF7/500), le SF n'y est pas conservé.
    """
    sf_up, _ = _sf_bw(AU915.dr_datr(tx_dr))
    sf_dl, bw_dl = _sf_bw(AU915.rx1(tx_dr, 0)[1])
    assert sf_dl == sf_up
    assert bw_dl == 500_000


# ---------------------------------------------------------------------------
# T-B1-3 — le DR de RX1 appartient bien à la plage descendante
# ---------------------------------------------------------------------------

def test_au_rx1_dr_in_downlink_range():
    for tx_dr in RX1_ATTENDU:
        dr = AU915.dr_of_downlink_datr(AU915.rx1(tx_dr, 0)[1])
        assert 8 <= dr <= 13, f"DR{tx_dr} → DR{dr} hors de la plage descendante"
    assert set(AU915._rx1_dr.values()) == set(RX1_ATTENDU.values())


# ---------------------------------------------------------------------------
# T-B1-10 — table des charges N complète
# ---------------------------------------------------------------------------

def test_au_max_payload_table():
    """N = M − 8. DR8 : M = 61, N = 53. DR9 : M = 137, N = 129.

    Les DR10 à DR13 portent un écart de 20 octets non résolu (hors lot I6-b1) ; ils sont
    donc assertés sur la valeur en vigueur, et non présentés comme conformes.
    """
    releve = {dr: AU915.max_frm_payload(dr) for dr in N_ATTENDU}
    assert releve == N_ATTENDU


def test_au_queue_limit_and_rx2():
    """La borne de file est la plus petite N des fenêtres RX1 atteignables, soit DR8."""
    assert AU915.queue_payload_max == 53
    assert AU915.dl_settings & 0x0F == 8


# ---------------------------------------------------------------------------
# T-B1-12 — même modulation ⇒ même N (garde-fou anti-récidive)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dr", [8, 9, 10, 11, 12, 13])
def test_downlink_payload_matches_shared_modulation(dr):
    """AU915 et US915 partagent les mêmes modulations descendantes : N doit être identique.

    C'est cette contradiction interne — DR8 valait 33 en AU915 et 53 en US915 pour un même
    SF12/500 — qui a révélé le second défaut.
    """
    assert AU915.dr_datr(dr) == US915.dr_datr(dr)
    assert AU915.max_frm_payload(dr) == US915.max_frm_payload(dr)


# ---------------------------------------------------------------------------
# T-B1-13 — le Join-Accept suit le DR de RX1, par le temps d'antenne
# ---------------------------------------------------------------------------

def test_au915_join_accept_airtime_follows_rx1():
    """Join-Accept n'emprunte pas la file : il n'est pas soumis à `queue_payload_max`.

    I6-b1 l'atteint par le temps d'antenne, puisque la fenêtre RX1 change de débit. Un
    terminal à SF12 reçoit désormais son Join-Accept en SF12/500 et non plus SF10/500 :
    l'occupation de la passerelle s'allonge d'un facteur supérieur à trois.
    """
    assert JOIN_ACCEPT_BYTES == 33      # PHYPayload complet, 17 octets sans CFList

    lent = _radio(AU915, 915_200_000, 12, 14.0)     # DR0 → RX1 DR8 (SF12/500)
    assert (lent.rx1_sf, lent.rx1_bw_hz) == (12, 500_000)
    t_sf12 = accept_airtime_ns(lent, RX1)
    assert t_sf12 > 0

    rapide = _radio(AU915, 915_200_000, 7, 14.0)    # DR5 → RX1 DR13 (SF7/500)
    assert (rapide.rx1_sf, rapide.rx1_bw_hz) == (7, 500_000)
    t_sf7 = accept_airtime_ns(rapide, RX1)

    # La même trame occupe bien plus longtemps au SF12 qu'au SF7 : le temps d'antenne suit
    # la fenêtre réellement émise.
    assert t_sf12 > 3 * t_sf7


# ---------------------------------------------------------------------------
# T-B1-4 — la fréquence RX1 ne dépend pas du débit (inchangé)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tx_ch,freq", [(0, 923.3), (7, 927.5), (8, 923.3), (70, 926.9)])
def test_au_rx1_channel_is_tx_channel_modulo_8(tx_ch, freq):
    assert AU915.rx1(0, tx_ch)[0] == pytest.approx(freq)


# ---------------------------------------------------------------------------
# T-B1-8 — traçabilité
# ---------------------------------------------------------------------------

def test_au915_traceability_header():
    """Le fichier régional porte sa référence normative, sa source et ses statuts."""
    import inspect

    source = inspect.getsource(__import__("lsim.au915", fromlist=["AU915"]))
    for mention in ("RP002-1.0.5", "table 44", "NORMATIF CONFIRMÉ",
                    "HYPOTHÈSE NON VÉRIFIÉE", "L1"):
        assert mention in source, f"mention de traçabilité absente : {mention!r}"


# ---------------------------------------------------------------------------
# T-B1-5 / T-B1-11 — parcours complet et file
# ---------------------------------------------------------------------------

def test_au915_end_to_end_join_ack_and_queue(tmp_path):
    env = Env(tmp_path, plan=AU915)
    addr, keys = env.join_device(dev_nonce=1)
    # Uplink confirmé sur 915,2 MHz (canal 0, DR0) : ACK en RX1 à 923,3 MHz / SF12 500 kHz.
    outcome = env.handle(up(keys, addr, 0, b"au", fport=1, confirmed=True, dr=0, ch=0),
                         freq=915.2, datr="SF12BW125")
    assert outcome.issue == "data_accepted"
    assert outcome.txpk.freq_mhz == pytest.approx(923.3)
    assert outcome.txpk.datr == "SF12BW500"
    assert open_dl(outcome.txpk, keys, conf=0, nfcnt=0).ack is True
    # File : 53 octets acceptés, 54 refusés (N de DR8, la fenêtre RX1 la plus étroite).
    env.store.enqueue_downlink(DEV, 1, False, b"\x00" * 53, AU915)
    with pytest.raises(ValueError):
        env.store.enqueue_downlink(DEV, 1, False, b"\x00" * 54, AU915)

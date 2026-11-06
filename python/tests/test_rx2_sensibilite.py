"""I3 — Sensibilité évaluée dans la fenêtre **réellement émise** (C4), sur plusieurs régions (C6).

Avant I3, les deux moteurs seuillaient une descente avec la sensibilité de RX1, quelle que soit la
fenêtre effectivement utilisée. Une descente repliée en RX2 au SF12BW125 s'entend 13 dB plus bas
qu'au SF7BW125 : elle était déclarée `lost_sensitivity` alors que le dispositif l'entendait.

**La parité ne disait rien de cette erreur — les deux moteurs la commettaient à l'identique.** Ces
tests exigent donc deux choses distinctes : que la décision suive la fenêtre émise, et que le cœur
C++ et l'oracle Python la prennent de la même façon.

Seuils de réception du cœur (dBm, BW125) : SF7 −123 · SF10 −132 · SF12 −136.

Référence : RP002-1.0.5, §3 normatif en cas de conflit. RX2 par défaut EU868 = 869,525 MHz
SF12BW125 ; `RECEIVE_DELAY2 = RECEIVE_DELAY1 + 1 s`.
"""

import pytest

from lsim.downlink_plan import plan_native_v2
from lsim.downlink_plan import DeviceRx2
from lsim.plan import get_plan
from lsim.radio import receiver_sensitivity_dbm
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import simulate_uplinks_trace
from lsim.trace_events import (DATA_FRAME_OVERHEAD_BYTES, DeviceRadio, ProtocolOptions,
                               _downlink_airtime_ns, _downlink_jobs, _events,
                               _schedule_gateway, _seuil_dispositif, device_radios)

SECONDE = 1_000_000_000
RX1_HZ = 868_100_000

# C6 : au moins quatre profils régionaux exercés, dont un en SF10. [H] — lus dans `lsim.plan`,
# pas recopiés : ce sont les valeurs du dépôt, pas une table recopiée de mémoire.
REGIONS = ("EU868", "US915", "AS923", "IN865", "AU915", "KR920", "RU864")


def _rx2_de_la_region(nom: str) -> tuple[int, int, int]:
    """(fréquence, SF, largeur de bande) de la fenêtre RX2 du profil régional."""
    import re

    hz, nom_dr = get_plan(nom).rx2()
    sf = int(re.search(r"SF(\d+)", nom_dr).group(1))
    bw = int(re.search(r"BW(\d+)", nom_dr).group(1)) * 1000
    return hz, sf, bw


def _radio(rx2_hz=869_525_000, rx2_sf=12, rx2_bw_hz=125_000, sf=7, tx_power_dbm=14.0):
    return DeviceRadio(freq_hz=RX1_HZ, dr=None, rx1_hz=RX1_HZ, tx_power_dbm=tx_power_dbm,
                       rx1_sf=sf, rx1_bw_hz=125_000, rx2_hz=rx2_hz, rx2_sf=rx2_sf,
                       rx2_bw_hz=rx2_bw_hz)


def _options(repli=True, every=1, payload=40, gain=0.0, offset=0.0):
    """Descentes de 40 octets à chaque uplink reçu : l'émetteur sature, des RX1 sont perdues.

    **40 octets, et non 200.** Les scènes portent une région, donc la validation transversale
    s'applique : RX2 tombe sur le DR de repli, dont N vaut 51 (EU868, AS923, IN865 — DR0 et
    DR2). À 200 octets le repli est refusé pour dépassement de capacité, et les tests ne
    démontrent plus rien. À 40 octets la contention est réelle **et** le repli reste
    physiquement possible (§23.8 : plafond du repli = N(RX2)).
    """
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=every,
                           downlink_payload_bytes=payload, gateway_tx_power_dbm=27.0,
                           device_antenna_gain_dbi=gain, device_rx_offset_db=offset,
                           rx2_fallback=repli)


def _scenario_sature(region="EU868"):
    # Fréquence montante du **premier canal du plan** : AS923 et IN865 n'ont pas 868,1 MHz, et le
    # scénario est rejeté à la validation si la fréquence est hors plan.
    canal = get_plan(region).uplink_channels_hz()[0]
    raw = {
        "schema_version": 1, "name": "rx2-sensibilite", "seed": 7,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": canal, "exponent": 2.7},
        "groups": [{
            "name": "g0", "count": 80, "region": region, "channel_freq_hz": canal,
            "placement": {"type": "disk", "radius_m": 800},
            "spreading_factor": 7, "payload_bytes": 20, "tx_power_dbm": 14.0,
            "period_s": 5, "messages": 10, "start_spread_s": 5,
        }],
    }
    scenario = Scenario(ScenarioModel.model_validate(raw))
    devices, _g, _i = scenario.deploy()
    result = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                    scenario.environment, gateway_busy=())
    return result.records, device_radios(scenario)


def _records_a_rssi(records, rssi_dbm: float):
    """Mêmes instants, même issue, mais un RSSI choisi — pour placer le lien dans la fenêtre voulue."""
    from lsim.simulator import TxRecord

    return [TxRecord(device_index=r.device_index, start_ns=r.start_ns, end_ns=r.end_ns,
                     spreading_factor=r.spreading_factor, outcome=r.outcome,
                     rssi_dbm=rssi_dbm)
            for r in records]


def _rx2_des_radios(radios):
    """Table RX2 telle que la construit l'appelant : une entrée par dispositif."""
    return tuple(DeviceRx2(rx2_hz=r.rx2_hz, rx2_sf=r.rx2_sf, rx2_bw_hz=r.rx2_bw_hz)
                 for r in radios)


def _sorts_descente(events) -> dict[tuple[int, int], str]:
    """Issue du saut passerelle → dispositif, indexée par (dispositif, instant d'émission)."""
    out = {}
    for e in events:
        for h in e.hops:
            if h.from_id == "gw:0":
                out[(e.device_index, h.t_ns)] = h.outcome
    return out


# --------------------------------------------------------------------------- l'unité : les seuils

def test_le_seuil_suit_la_fenetre():
    """`_seuil_dispositif` rend le seuil de RX1, ou celui de RX2 quand la descente y est émise."""
    radio = _radio(rx2_sf=12, rx2_bw_hz=125_000, sf=7)
    options = _options()
    assert _seuil_dispositif(radio, options, en_rx2=False) == pytest.approx(-123.0)
    assert _seuil_dispositif(radio, options, en_rx2=True) == pytest.approx(-136.0)
    # 13 dB d'écart : c'est la marge dans laquelle une descente RX2 était déclarée perdue à tort.
    delta = _seuil_dispositif(radio, options, False) - _seuil_dispositif(radio, options, True)
    assert delta == pytest.approx(13.0)


def test_sans_fenetre_rx2_le_seuil_reste_celui_de_rx1():
    """Sans fréquence ni SF de repli, il n'y a rien à émettre : le seuil RX2 n'est pas inventé."""
    options = _options()
    for partiel in (_radio(rx2_hz=0, rx2_sf=12), _radio(rx2_hz=869_525_000, rx2_sf=0)):
        assert not partiel.rx2_disponible
        assert _seuil_dispositif(partiel, options, en_rx2=True) == pytest.approx(-123.0)


# ------------------------------------------------------------ la fenêtre émise décide de la réception

def test_une_descente_en_rx2_est_entendue_la_ou_rx1_etait_sourde():
    """C4 : même RSSI, deux verdicts — perdue en RX1, reçue en RX2.

    Le RSSI descendant vaut `rssi + 13 dB` (P_gw 27 dBm − P_dev 14 dBm). À −142 dBm il tombe à
    −129 dBm : sourd au seuil RX1 (−123), audible au seuil RX2 (−136). Le test épingle les deux
    verdicts sur la **même** trace, la seule différence étant la fenêtre réellement émise.
    """
    records, radios = _scenario_sature()
    records = _records_a_rssi(records, rssi_dbm=-142.0)
    options = _options()

    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, _busy = _schedule_gateway(jobs, options)
    assert fenetres.count("rx2") > 0, "le repli n'a jamais été exercé : test inutile"

    # Comportement d'avant I3, conservé quand l'appelant ne fournit pas les options.
    sorts_avant = _sorts_descente(
        _events(records, radios, jobs, starts, [False] * len(records), None, fenetres))
    # Comportement I3 : le seuil est celui de la fenêtre émise.
    sorts_apres = _sorts_descente(
        _events(records, radios, jobs, starts, [False] * len(records), None, fenetres, options))

    emis_rx2 = [k for k, f in enumerate(fenetres) if f == "rx2" and starts[k] is not None]
    assert emis_rx2
    for k in emis_rx2:
        cle = (jobs[k].device, starts[k])
        assert sorts_avant[cle] == "lost_sensitivity"   # l'erreur des deux moteurs avant I3
        assert sorts_apres[cle] == "delivered"          # corrigée

    # Une descente restée en RX1, elle, est toujours perdue : le correctif est ciblé sur RX2.
    emis_rx1 = [k for k, f in enumerate(fenetres) if f == "rx1" and starts[k] is not None]
    assert emis_rx1
    for k in emis_rx1:
        cle = (jobs[k].device, starts[k])
        assert sorts_apres[cle] == sorts_avant[cle] == "lost_sensitivity"


def test_la_marge_de_reception_rx2_est_celle_du_lien():
    """Un RSSI franchement sous le seuil RX2 reste perdu : la correction n'est pas un passe-droit."""
    records, radios = _scenario_sature()
    records = _records_a_rssi(records, rssi_dbm=-155.0)   # rssi_dl = −142 dBm
    options = _options()
    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, _busy = _schedule_gateway(jobs, options)
    sorts = _sorts_descente(
        _events(records, radios, jobs, starts, [False] * len(records), None, fenetres, options))
    emis = [(jobs[k].device, starts[k]) for k in range(len(jobs)) if starts[k] is not None]
    assert emis
    assert all(sorts[cle] == "lost_sensitivity" for cle in emis), \
        "sous le seuil RX2, la descente doit rester perdue"


# --------------------------------------------------------------------------------- parité avec le cœur

def test_parite_coeur_oracle_sur_la_sensibilite_rx2():
    """C4 + C5 : le cœur C++ prend la même décision que l'oracle, au saut près.

    C'est le test que la parité **seule** ne donnait pas : les deux moteurs pouvaient s'entendre
    sur une erreur. On les exige ici d'accord sur la correction.
    """
    records, radios = _scenario_sature()
    records = _records_a_rssi(records, rssi_dbm=-142.0)
    options = _options()

    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, busy = _schedule_gateway(jobs, options)
    oracle = (_events(records, radios, jobs, starts, [False] * len(records), None, fenetres,
                      options), tuple(busy))

    coeur = plan_native_v2(records, radios, options, _rx2_des_radios(radios))

    assert fenetres.count("rx2") > 0, "le repli n'a jamais été exercé : test inutile"
    assert coeur == oracle, "divergence cœur/oracle sur la sensibilité de la fenêtre émise"


# ---------------------------------------------------------------------------------- C6 : multi-régions

@pytest.mark.parametrize("region", REGIONS)
def test_le_seuil_rx2_est_celui_du_profil_regional(region):
    """C6 : chaque profil impose son propre seuil de repli — pas un SF12 générique.

    AS923 et IN865 replient en SF10BW125 (−132 dBm), US915 et AU915 en SF12BW500 (−130 dBm) :
    traiter toutes les régions au SF12BW125 donnerait un seuil faux de 4 à 6 dB.
    """
    hz, sf, bw = _rx2_de_la_region(region)
    radio = _radio(rx2_hz=hz, rx2_sf=sf, rx2_bw_hz=bw, sf=7)
    options = _options()
    assert radio.rx2_disponible
    assert _seuil_dispositif(radio, options, en_rx2=True) == pytest.approx(
        receiver_sensitivity_dbm(sf, bw))
    assert _seuil_dispositif(radio, options, en_rx2=False) == pytest.approx(
        receiver_sensitivity_dbm(7, 125_000))


def test_les_profils_ne_se_replient_pas_tous_au_meme_debit():
    """Garde-fou du tableau ci-dessus : au moins un profil en SF10 et un autre en BW500.

    Si tous les profils partageaient le même RX2, le test paramétré précédent ne prouverait rien
    de plus qu'un test à une région.
    """
    profils = {r: _rx2_de_la_region(r) for r in REGIONS}
    assert len(profils) >= 4
    assert any(sf == 10 for _hz, sf, _bw in profils.values()), "aucun profil en SF10"
    assert any(bw == 500_000 for _hz, _sf, bw in profils.values()), "aucun profil en BW500"
    assert any(sf == 12 and bw == 125_000 for _hz, sf, bw in profils.values())


@pytest.mark.parametrize("region", ("EU868", "AS923", "IN865"))
def test_repli_effectif_sur_plusieurs_regions(region):
    """C6 : le repli aboutit, à la fréquence et à la durée du profil, sur une vraie trace.

    Limité aux régions dont RX2 est en BW125 : la scène est calibrée sur une bande de 125 kHz,
    et l'exercice d'une autre largeur relève d'un réglage de scène, pas du mécanisme de repli.
    """
    hz, sf, bw = _rx2_de_la_region(region)
    assert bw == 125_000
    records, radios = _scenario_sature(region=region)
    assert radios[0].rx2_hz == hz
    assert radios[0].rx2_sf == sf

    records = _records_a_rssi(records, rssi_dbm=-142.0)
    options = _options()
    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, busy = _schedule_gateway(jobs, options)

    emis_rx2 = [k for k, f in enumerate(fenetres) if f == "rx2" and starts[k] is not None]
    assert emis_rx2, f"{region} : le repli n'a jamais été exercé"
    # Fréquence de la fenêtre de secours, et durée d'antenne du débit de cette fenêtre.
    assert all(jobs[k].rx2_hz == hz for k in emis_rx2)
    # Taille de trame dérivée des options, et non figée : la charge a été recalibrée sous
    # N(RX2) pour que le repli reste physiquement possible (voir `_options`).
    trame = DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes + len(jobs[emis_rx2[0]].fopts)
    air_rx2 = {_downlink_airtime_ns(radios[jobs[k].device], trame, "rx2") for k in emis_rx2}
    assert air_rx2 <= {b - a for a, b in busy}
    # Et le cœur est d'accord, au saut près.
    coeur = plan_native_v2(records, radios, options, _rx2_des_radios(radios))
    oracle = (_events(records, radios, jobs, starts, [False] * len(records), None, fenetres,
                      options), tuple(busy))
    assert coeur == oracle


# ------------------------------------------------------------------------------------- C7 : le coût

def test_le_repli_coute_l_emetteur_mesure():
    """C7 : rattraper en RX2 occupe l'émetteur plus longtemps — mesure, pas jugement.

    Chiffre épinglé pour qu'une régression de placement ne passe pas inaperçue. Au SF12BW125, la
    même trame coûte une vingtaine de fois plus de temps d'antenne qu'au SF7BW125.
    """
    radio = _radio(rx2_sf=12, rx2_bw_hz=125_000, sf=7)
    air_rx1 = _downlink_airtime_ns(radio, 200 + 13, "rx1")
    air_rx2 = _downlink_airtime_ns(radio, 200 + 13, "rx2")
    assert air_rx2 > air_rx1
    rapport = air_rx2 / air_rx1
    assert 15.0 < rapport < 30.0, f"rapport inattendu : {rapport:.2f}"

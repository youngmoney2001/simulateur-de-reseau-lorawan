"""I5-a — débit réel des fenêtres RX1/RX2 dans le chemin multi-passerelles.

Portée : l'écart n°1 de l'audit (docs/I5_AUDIT_MULTI.md §3). Le moteur réservait le temps
d'antenne RX1 au **SF montant, à 125 kHz**, au lieu du débit de la fenêtre qui émet. Passer
une table de radios corrige le temps d'antenne **et** la sensibilité de réception descendante.

Propriétés vérifiées ici (plan docs/I5_A_RX1_AIRTIME.md §6) :

    T-A-1  sans table : résultats identiques à l'entrée historique
    T-A-2  table sur la diagonale (RX1 = SF montant, 125 kHz) : résultats identiques
    T-A-3  hors diagonale : le temps d'antenne est celui de la fenêtre (mesuré)
    T-A-5  struct_size / abi_version / reserved non nul : refus
    T-A-6  comptes incohérents : refus
    T-A-8  table rx2 avec rule.rx2_sf != 0 : refus explicite

T-A-3, T-A-4 et T-A-7 sont vérifiés côté C++ dans core/tests/test_multi_dl_rx1.cpp.

Aucune affirmation régionale ici : on ne dit pas quel DR impose chaque région, on vérifie que
le débit **demandé** est celui **appliqué**.
"""

import ctypes

import pytest

from lsim._native import (LIB, _CDownlinkRecord, _CDownlinkRule, _CDeviceStats, _CEndDevice,
                          _CGateway, _CGatewayRxStats, _CMultiDlArgs, _CMultiTxRecord,
                          _CNetworkStats, _CPropagation)
from lsim.downlink_plan import DeviceRx2
from lsim.lora import RadioConfig, time_on_air_ns
from lsim.simulator import (DownlinkRule, EndDevice, Gateway, Propagation,
                           simulate_multi_downlinks)
from lsim.trace_events import DeviceRadio

# Charge d'un ACK de données : kAckFrameBytes (12) côté moteur.
K_ACK_BYTES = 12


def _flotte(sf=10, n=1, messages=2):
    return [EndDevice(0.0, 100.0 * k, spreading_factor=sf, payload_bytes=20, messages=messages,
                      period_ns=60_000_000_000)
            for k in range(n)]


PASSES = [Gateway(0.0, 0.0)]
PROPAGATION = Propagation(frequency_hz=868_100_000)


def _airtime(sf, bw_hz, charge=K_ACK_BYTES):
    """Temps d'antenne LoRaWAN de référence, LDRO compris comme le moteur."""
    ldro = (2 ** sf / bw_hz) * 1e9 > 16_000_000
    return time_on_air_ns(RadioConfig(sf, bandwidth_hz=bw_hz, coding_rate=1, crc_on=False,
                                      explicit_header=True, low_data_rate_optimize=ldro),
                          charge)


def _duree_premiere_descente(resultat):
    for d in resultat.downlinks:
        if d.start_ns >= 0:
            return d.end_ns - d.start_ns
    return None


# --------------------------------------------------------------------------- T-A-1, T-A-2


def test_sans_table_les_resultats_sont_ceux_de_lentree_historique():
    """T-A-1 : aucune table transmise ⇒ l'entrée `_multi_dl` historique est conservée.

    C'est la garantie de non-régression de tout le jalon : le chemin sans table ne doit pas
    avoir bougé d'un nanoseconde.
    """
    devs, regle = _flotte(), DownlinkRule(ack_uplinks=True, payload_bytes=0, rx2_sf=0)
    r = simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle)
    attendu = _airtime(10, 125_000)  # hypothèse historique : RX1 au SF montant, 125 kHz
    assert _duree_premiere_descente(r) == attendu


@pytest.mark.parametrize("sf", [7, 9, 12])
def test_table_sur_la_diagonale_ne_change_rien(sf):
    """T-A-2 : RX1 = (SF montant, 125 kHz) ⇒ résultats identiques, pour chaque SF.

    La diagonale de la table de sensibilité : c'est le cas où l'hypothèse historique se
    trouvait exacte. Toute divergence signalerait une régression.
    """
    devs = _flotte(sf=sf)
    regle = DownlinkRule(ack_uplinks=True, payload_bytes=0, rx2_sf=0)
    radios = [DeviceRadio(freq_hz=868_100_000, dr=0, rx1_hz=868_100_000, rx1_sf=sf,
                          rx1_bw_hz=125_000)]
    rx2 = [DeviceRx2(rx2_hz=869_525_000, rx2_sf=0, rx2_bw_hz=125_000)]
    sans = simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle)
    avec = simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle, radios=radios, rx2=rx2)
    assert avec.network == sans.network
    assert avec.downlinks == sans.downlinks
    assert avec.trace == sans.trace


# --------------------------------------------------------------------------- T-A-3


@pytest.mark.parametrize("sf,bw_hz", [(7, 500_000), (9, 250_000), (12, 125_000),
                                       (7, 125_000), (12, 500_000)])
def test_hors_diagonale_le_temps_dantenne_est_celui_de_la_fenetre(sf, bw_hz):
    """T-A-3 : le temps d'antenne réservé suit la table, pas le SF montant.

    C'est la correction elle-même, mesurée au nanoseconde contre un calcul indépendant.
    """
    devs = _flotte(sf=10)  # SF montant 10 : hors diagonale pour tous les cas ci-dessus
    regle = DownlinkRule(ack_uplinks=True, payload_bytes=0, rx2_sf=0)
    radios = [DeviceRadio(freq_hz=868_100_000, dr=0, rx1_hz=868_100_000, rx1_sf=sf,
                          rx1_bw_hz=bw_hz)]
    rx2 = [DeviceRx2(rx2_hz=869_525_000, rx2_sf=0, rx2_bw_hz=125_000)]
    r = simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle, radios=radios, rx2=rx2)
    assert _duree_premiere_descente(r) == _airtime(sf, bw_hz)


def test_lecart_est_mesurable_et_non_trivial():
    """T-A-3 : l'écart corrigé est d'un facteur ~28 sur un SF montant 10 — pas un arrondi.

    Sans cette amplitude, un test de non-régression passerait alors que le défaut est là.
    """
    devs = _flotte(sf=10)
    regle = DownlinkRule(ack_uplinks=True, payload_bytes=0, rx2_sf=0)
    radios = [DeviceRadio(freq_hz=868_100_000, dr=0, rx1_hz=868_100_000, rx1_sf=7,
                          rx1_bw_hz=500_000)]
    rx2 = [DeviceRx2(rx2_hz=869_525_000, rx2_sf=0, rx2_bw_hz=125_000)]
    sans = simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle)
    avec = simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle, radios=radios, rx2=rx2)
    rapport = _duree_premiere_descente(sans) / _duree_premiere_descente(avec)
    assert rapport == pytest.approx(28.02, abs=0.01)


# --------------------------------------------------------------------------- T-A-5, T-A-6, T-A-8


def _enveloppe_valide():
    """Enveloppe complète et correcte : **doit** renvoyer le statut 0.

    C'est le contrôle positif de tous les tests de refus ci-dessous. Sans lui, une enveloppe de
    pointeurs nuls échouerait pour une raison sans rapport, et le test ne testerait rien.
    """
    n, cap = 1, 8
    devs = (_CEndDevice * n)()
    devs[0].spreading_factor = 10
    devs[0].payload_bytes = 20
    devs[0].period_ns = 60_000_000_000
    devs[0].messages = 2
    devs[0].duty_cycle = 1.0
    gws = (_CGateway * 1)()
    gws[0].antenna_gain_dbi = 2.15
    prop = _CPropagation(868_100_000, 1000.0, 2.7, 6.0, 0.0, 0)
    rule = _CDownlinkRule(1, 1, 0, 27.0, 0.0, 0.0, 0, 0)
    st = (_CDeviceStats * n)()
    tot = _CNetworkStats()
    gst = (_CGatewayRxStats * 1)()
    rec = (_CMultiTxRecord * cap)()
    rc = ctypes.c_size_t(0)
    dl = (_CDownlinkRecord * cap)()
    dc = ctypes.c_size_t(0)
    a = _CMultiDlArgs()
    a.struct_size = ctypes.sizeof(_CMultiDlArgs)
    a.abi_version = 1
    a.devices, a.device_count = devs, n
    a.gateways, a.gateway_count = gws, 1
    a.prop, a.rule = ctypes.pointer(prop), ctypes.pointer(rule)
    a.per_device = st
    a.totals, a.per_gateway = ctypes.pointer(tot), gst
    a.records, a.record_capacity = rec, cap
    a.record_count = ctypes.pointer(rc)
    a.downlinks, a.downlink_capacity = dl, cap
    a.downlink_count = ctypes.pointer(dc)
    # garde-fou : les tableaux doivent survivre à l'appel
    return a, (devs, gws, prop, rule, st, tot, gst, rec, rc, dl, dc)


def _statut(a, _keep):
    return LIB.lsim_simulate_uplinks_multi_dl_env(ctypes.byref(a))


def test_enveloppe_valide_reussit_controle_positif():
    """T-A-5 : contrôle positif — une enveloppe correcte renvoie 0.

    Sans ce test, tous les refus ci-dessous passeraient même si l'enveloppe était cassée pour
    une raison sans rapport (pointeurs nuls).
    """
    a, keep = _enveloppe_valide()
    assert _statut(a, keep) == 0


def test_enveloppe_nulle_est_refusee():
    """T-A-5 : un pointeur nul est refusé, pas traité comme une enveloppe vide."""
    assert LIB.lsim_simulate_uplinks_multi_dl_env(None) != 0


def test_struct_size_et_abi_version_sont_verifies():
    """T-A-5 : une ABI future doit être refusée, pas servie comme si de rien n'était (O1)."""
    a, keep = _enveloppe_valide()
    a.struct_size -= 8
    assert _statut(a, keep) != 0

    a, keep = _enveloppe_valide()
    a.abi_version = 2
    assert _statut(a, keep) != 0

    a, keep = _enveloppe_valide()
    a.abi_version = 0
    assert _statut(a, keep) != 0


def test_reserved_non_nul_est_refuse():
    """T-A-5 : `reserved` renseigné ⇒ refus. L'ignorer serait un repli silencieux (bbb3)."""
    for i in (0, 1):
        a, keep = _enveloppe_valide()
        a.reserved[i] = 1
        assert _statut(a, keep) != 0, f"reserved[{i}] non vérifié"


def test_une_seule_table_est_refusee():
    """T-A-6 : radios sans rx2, ou l'inverse ⇒ refus.

    Corriger RX1 seul serait légitime en soi ; mais deux compteurs pour deux tables qui
    doivent toujours aller de pair ouvriraient une combinaison jamais testée.
    """
    devs = _flotte(sf=10, n=2)
    regle = DownlinkRule(ack_uplinks=True, payload_bytes=0, rx2_sf=0)
    radios = [DeviceRadio(freq_hz=868_100_000, dr=0, rx1_hz=868_100_000, rx1_sf=7,
                          rx1_bw_hz=500_000)] * 2
    rx2 = [DeviceRx2(rx2_hz=869_525_000, rx2_sf=0, rx2_bw_hz=125_000)] * 2
    with pytest.raises(Exception):
        # radios sans rx2 : refusé côté Python avant même l'appel natif
        simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle, radios=radios)
    with pytest.raises(Exception):
        simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle, rx2=rx2)


def test_compte_incoherent_est_refuse():
    """T-A-6 : une entrée par dispositif, pas une de moins."""
    devs = _flotte(sf=10, n=3)
    regle = DownlinkRule(ack_uplinks=True, payload_bytes=0, rx2_sf=0)
    radios = [DeviceRadio(freq_hz=868_100_000, dr=0, rx1_hz=868_100_000, rx1_sf=7,
                          rx1_bw_hz=500_000)] * 2  # 2 pour 3 dispositifs
    rx2 = [DeviceRx2(rx2_hz=869_525_000, rx2_sf=0, rx2_bw_hz=125_000)] * 3
    with pytest.raises(ValueError, match="une entrée par dispositif"):
        simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle, radios=radios, rx2=rx2)


def test_comptes_de_tables_incoherents_refuses_par_le_coeur():
    """T-A-6 : le cœur refuse des comptes incohérents, sans lire les tables.

    Testé **via l'enveloppe**, en contournant le pont Python : celui-ci valide déjà
    `len(radios) == device_count` et lèverait avant d'appeler le natif. La défense du cœur est
    donc distincte de celle du pont, et seule cette écriture l'exerce.
    """
    from lsim._native import _CPlanDevice, _CPlanDeviceRx2

    n = 2
    devs = [_CEndDevice() for _ in range(n)]
    for d in devs:
        d.spreading_factor, d.payload_bytes = 10, 20
        d.period_ns, d.messages, d.duty_cycle = 60_000_000_000, 2, 1.0
    radios = (_CPlanDevice * n)()
    rx2 = (_CPlanDeviceRx2 * n)()
    for i in range(n):
        radios[i].rx1_sf, radios[i].rx1_bw_hz = 7, 500_000

    a, keep = _enveloppe_valide()
    c_devs = (_CEndDevice * n)(*devs)
    st = (_CDeviceStats * n)()
    a.devices, a.device_count, a.per_device = c_devs, n, st
    a.radios, a.radio_count = radios, n
    a.rx2, a.rx2_count = rx2, n - 1  # un compte de moins : refusé par le cœur
    assert _statut(a, keep + (c_devs, st, radios, rx2)) != 0


def test_table_rx2_avec_rx2_sf_non_nul_est_refusee():
    """T-A-8 : une même grandeur exprimée à deux endroits est une ambiguïté, pas une redondance.

    Décision i5-a-2. Précédent : `lsim_gateway_v2` exige déjà un scalaire historique neutre
    sous le modèle absolu.
    """
    devs = _flotte(sf=10)
    regle = DownlinkRule(ack_uplinks=True, payload_bytes=0, rx2_sf=12)  # scalaire ET table
    radios = [DeviceRadio(freq_hz=868_100_000, dr=0, rx1_hz=868_100_000, rx1_sf=7,
                          rx1_bw_hz=500_000)]
    rx2 = [DeviceRx2(rx2_hz=869_525_000, rx2_sf=12, rx2_bw_hz=125_000)]
    with pytest.raises(Exception):  # StatusError du cœur
        simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle, radios=radios, rx2=rx2)


def test_table_rx2_avec_rx2_sf_nul_est_acceptee():
    """T-A-8 : `rx2_sf == 0` ⇒ la table est la seule source, le repli est évalué."""
    devs = _flotte(sf=10)
    regle = DownlinkRule(ack_uplinks=True, payload_bytes=0, rx2_sf=0)
    radios = [DeviceRadio(freq_hz=868_100_000, dr=0, rx1_hz=868_100_000, rx1_sf=7,
                          rx1_bw_hz=500_000)]
    rx2 = [DeviceRx2(rx2_hz=869_525_000, rx2_sf=12, rx2_bw_hz=125_000)]
    r = simulate_multi_downlinks(devs, PASSES, PROPAGATION, regle, radios=radios, rx2=rx2)
    assert r.downlinks, "aucune descente : le test ne testerait rien"


# --------------------------------------------------------------------------- cohérence de l'ABI


def test_la_disposition_ctypes_concorde_avec_le_c():
    """La structure ctypes doit avoir la taille que les static_assert du C++ gèlent (232 o)."""
    assert ctypes.sizeof(_CMultiDlArgs) == 232

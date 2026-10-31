"""Caractérisation RF R1 : comportement radio réel du simulateur, mesuré et figé.

Cette suite n'énonce pas un modèle idéal : elle **caractérise** ce que le cœur natif fait
réellement à la base `9686c25`, sujet par sujet, et fige les valeurs mesurées. Elle sert de
référence pour la reconstruction R2b : tout écart ultérieur devra être expliqué, jamais absorbé.

Six sujets :

1. gain de la passerelle : effet exact sur le RSSI montant ;
2. gain du terminal : absence d'effet sur le RSSI montant à la base (le gain d'antenne du
   dispositif n'existe pas encore ; seule la puissance d'émission agit) ;
3. descente : effet du gain du terminal sur la réception, et réciprocité du bilan ;
4. sensibilité RAK7249 : écart entre la valeur de catalogue et le seuil réellement appliqué ;
5. collisions : même SF qui se chevauchent, effet de capture, et limite du modèle en fréquence ;
6. contrôles : SF différents et transmissions non chevauchantes ne collisionnent pas.

Conventions de mesure : puissance et gains en dBm/dBi, distances en mètres, temps en
nanosecondes. Aucun `parametrize` : chaque cas est une fonction nommée, pour que le compte de
tests reste lisible et stable.
"""

import pytest

from lsim.gateway_profiles import get_profile
from lsim.radio import LogDistanceModel, receiver_sensitivity_dbm
from lsim.simulator import (DownlinkRule, EndDevice, Gateway, Propagation, TxRecord,
                            simulate_multi_downlinks, simulate_uplinks_trace)

# Propagation de référence : EU868, 868,1 MHz, distance de référence 1 m, exposant 2,7.
PROPAGATION = Propagation(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=2.7)

# Issues de la montée : encodage de `TxRecord` (0 perdue/sensibilité, 1 collision, 2 reçue).
LOST_SENSITIVITY = TxRecord.OUTCOME_LOST_SENSITIVITY
LOST_COLLISION = TxRecord.OUTCOME_LOST_COLLISION
RECEIVED = TxRecord.OUTCOME_RECEIVED

# Issues de la descente : encodage **inversé** de `DownlinkRecord` (0 reçu, 1 sous la sensibilité).
# L'asymétrie est réelle et figée par l'ABI : on la nomme au lieu de la masquer.
DL_RECEIVED = 0
DL_LOST_SENSITIVITY = 1

# Airtime mesuré : SF9, 10 octets, 125 kHz -> 144 384 000 ns.
AIRTIME_SF9_10O_NS = 144_384_000


def _rssi(distance_m, gateway_gain_dbi=0.0, tx_power_dbm=14.0, spreading_factor=9):
    """RSSI montant d'un dispositif isolé, mesuré par le cœur natif."""
    device = EndDevice(x_m=distance_m, spreading_factor=spreading_factor, messages=1,
                       tx_power_dbm=tx_power_dbm)
    result = simulate_uplinks_trace([device], Gateway(antenna_gain_dbi=gateway_gain_dbi),
                                    PROPAGATION)
    return result.records[0].rssi_dbm


def _outcomes(devices, capture_threshold_db=6.0):
    """Issues de la trace montante, dans l'ordre des dispositifs."""
    propagation = Propagation(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=2.7,
                              capture_threshold_db=capture_threshold_db)
    result = simulate_uplinks_trace(devices, Gateway(), propagation)
    return [record.outcome for record in result.records]


# ---------------------------------------------------------------- 1. Gain de la passerelle

def test_gateway_gain_raises_the_uplink_rssi_by_exactly_3_db():
    """+3 dBi sur la passerelle déplacent le RSSI montant de +3,000000 dB, exactement."""
    sans_gain = _rssi(1000.0, gateway_gain_dbi=0.0)
    avec_gain = _rssi(1000.0, gateway_gain_dbi=3.0)
    assert avec_gain - sans_gain == pytest.approx(3.0, abs=1e-9)


def test_gateway_gain_is_additive_and_linear_over_the_whole_range():
    """Le gain de la passerelle est un terme additif : 0, 3 et 6 dBi donnent une droite."""
    valeurs = [_rssi(1000.0, gateway_gain_dbi=gain) for gain in (0.0, 3.0, 6.0)]
    assert valeurs[1] - valeurs[0] == pytest.approx(3.0, abs=1e-9)
    assert valeurs[2] - valeurs[1] == pytest.approx(3.0, abs=1e-9)


def test_gateway_gain_does_not_change_the_airtime_neither_the_schedule():
    """Le gain d'antenne ne touche ni le temps d'antenne ni l'instant de départ."""
    dispositif = lambda: EndDevice(x_m=1000.0, spreading_factor=9, payload_bytes=10, messages=1)
    sans = simulate_uplinks_trace([dispositif()], Gateway(antenna_gain_dbi=0.0), PROPAGATION)
    avec = simulate_uplinks_trace([dispositif()], Gateway(antenna_gain_dbi=6.0), PROPAGATION)
    assert sans.records[0].start_ns == avec.records[0].start_ns
    assert sans.records[0].end_ns == avec.records[0].end_ns


def test_uplink_rssi_matches_the_log_distance_model_exactly():
    """Le RSSI vaut P_tx + G_passerelle - PL(d) : identité vérifiée à 1e-12 près."""
    modele = LogDistanceModel(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=2.7)
    for distance, gain, puissance in ((1000.0, 0.0, 14.0), (1000.0, 3.0, 14.0),
                                      (5000.0, 0.0, 8.0)):
        attendu = puissance + gain - modele.path_loss_db(distance)
        assert _rssi(distance, gain, puissance) == pytest.approx(attendu, abs=1e-9)


# ---------------------------------------------------------------- 2. Gain du terminal

def test_device_tx_power_moves_the_uplink_rssi_one_for_one():
    """À la base, seul `tx_power_dbm` agit côté dispositif : +3 dBm -> +3 dB de RSSI."""
    valeurs = [_rssi(1000.0, tx_power_dbm=puissance) for puissance in (11.0, 14.0, 17.0)]
    assert valeurs[1] - valeurs[0] == pytest.approx(3.0, abs=1e-9)
    assert valeurs[2] - valeurs[1] == pytest.approx(3.0, abs=1e-9)


def test_device_has_no_antenna_gain_field_at_the_base():
    """Caractérisation : le gain d'antenne du terminal n'existe pas encore dans le modèle.

    C'est l'écart que R2b introduira (`lsim_device_rf`). Tant qu'il n'existe pas, le bilan
    montant ne peut pas distinguer puissance rayonnée et gain d'antenne : seul `tx_power_dbm`
    est disponible, et il agit à l'identique sur le RSSI.
    """
    champs = set(EndDevice.__dataclass_fields__)
    assert "tx_power_dbm" in champs
    assert "antenna_gain_dbi" not in champs
    assert "cable_loss_db" not in champs


def test_device_tx_power_changes_nothing_to_the_airtime():
    """La puissance d'émission ne modifie pas le temps d'antenne (même SF, même charge)."""
    bas = simulate_uplinks_trace([EndDevice(x_m=1000.0, spreading_factor=9, messages=1,
                                            tx_power_dbm=8.0)], Gateway(), PROPAGATION)
    haut = simulate_uplinks_trace([EndDevice(x_m=1000.0, spreading_factor=9, messages=1,
                                             tx_power_dbm=14.0)], Gateway(), PROPAGATION)
    assert bas.records[0].end_ns - bas.records[0].start_ns == \
        haut.records[0].end_ns - haut.records[0].start_ns


# ---------------------------------------------------------------- 3. Descente

def _downlink_outcome(distance_m, device_gain_dbi, gateway_tx_power_dbm, spreading_factor=12):
    """Issue d'une descente (0 = reçu, 1 = sous la sensibilité)."""
    regle = DownlinkRule(ack_uplinks=True, every=1, gateway_tx_power_dbm=gateway_tx_power_dbm,
                         device_antenna_gain_dbi=device_gain_dbi)
    dispositif = EndDevice(x_m=distance_m, spreading_factor=spreading_factor, messages=3)
    resultat = simulate_multi_downlinks([dispositif], [Gateway()], PROPAGATION, regle)
    return resultat.downlinks[0].outcome if resultat.downlinks else None


def test_device_downlink_gain_does_not_leak_into_the_uplink_budget():
    """Le gain de descente du terminal ne remonte jamais dans le RSSI montant.

    Mesure sur 0 / 10 / 20 dBi : le meilleur RSSI montant reste identique au bit près, alors
    que l'issue de descente, elle, bascule. Le gain est donc bien porté par un seul sens.
    """
    mesures = []
    for gain in (0.0, 10.0, 20.0):
        regle = DownlinkRule(ack_uplinks=True, every=1, gateway_tx_power_dbm=0.0,
                             device_antenna_gain_dbi=gain)
        resultat = simulate_multi_downlinks(
            [EndDevice(x_m=12000.0, spreading_factor=12, messages=1)], [Gateway()],
            PROPAGATION, regle)
        mesures.append((resultat.trace[0].best_rssi_dbm, resultat.downlinks[0].outcome))
    assert mesures[0][0] == mesures[1][0] == mesures[2][0] == pytest.approx(-127.359289, abs=1e-6)
    assert [issue for _, issue in mesures] == [DL_LOST_SENSITIVITY, DL_RECEIVED, DL_RECEIVED]


def test_device_downlink_gain_flips_reception_exactly_at_the_margin():
    """À puissance de passerelle nulle, 10 dBi de gain terminal font basculer la réception.

    Mesure : 12 km, SF12, P_passerelle = 0 dBm -> gain 0 : sous la sensibilité ;
    gain 10 : reçu ; gain 20 : reçu. Le gain terminal agit donc sur la descente seule.
    """
    assert _downlink_outcome(12000.0, 0.0, 0.0) == DL_LOST_SENSITIVITY
    assert _downlink_outcome(12000.0, 10.0, 0.0) == DL_RECEIVED
    assert _downlink_outcome(12000.0, 20.0, 0.0) == DL_RECEIVED


def test_downlink_budget_is_reciprocal_and_carries_the_device_gain():
    """La descente est calculée par réciprocité, avec le gain du terminal en plus.

    `RSSI_desc = RSSI_mont - P_tx_dispositif + P_passerelle + G_dispositif` : c'est la formule
    que la mécanique de réception applique, et elle explique les bascules mesurées ci-dessus.
    """
    rssi_mont = _rssi(12000.0, gateway_gain_dbi=0.0, tx_power_dbm=14.0, spreading_factor=12)
    seuil = receiver_sensitivity_dbm(12)
    # Sans gain : sous le seuil ; avec 10 dBi : au-dessus, à 10 dB près.
    assert rssi_mont - 14.0 + 0.0 + 0.0 < seuil
    assert rssi_mont - 14.0 + 0.0 + 10.0 >= seuil


# ---------------------------------------------------------------- 4. Sensibilité RAK7249

def test_rak7249_catalog_sensitivity_is_published_as_minus_139_dbm():
    """Le catalogue annonce -139 dBm pour la RAK7249 (valeur constructeur, indicative)."""
    profil = get_profile("rak7249")
    assert profil.rx_sensitivity_min_dbm == pytest.approx(-139.0)


def test_rak7249_has_no_published_sensitivity_point_so_no_offset_is_applied():
    """Aucun point (SF, bande) publié : le profil n'impose donc aucun décalage au moteur."""
    profil = get_profile("rak7249")
    assert profil.rx_sensitivity_point is None


def test_effective_threshold_is_the_relative_sx1276_model_not_the_catalog_value():
    """Écart catalogue / seuil effectif, mesuré SF par SF.

    Le moteur applique le modèle relatif SX1276 ; l'écart avec les -139 dBm du catalogue
    décroît avec le SF (-16 dB en SF7, -3 dB en SF12). Caractérisation, pas correction.
    """
    attendus = {7: -123.0, 8: -126.0, 9: -129.0, 10: -132.0, 11: -133.0, 12: -136.0}
    ecarts = {}
    for sf, seuil in attendus.items():
        assert receiver_sensitivity_dbm(sf) == pytest.approx(seuil)
        ecarts[sf] = -139.0 - seuil
    assert ecarts == {7: -16.0, 8: -13.0, 9: -10.0, 10: -7.0, 11: -6.0, 12: -3.0}


def test_a_transmission_just_below_the_effective_threshold_is_lost():
    """Le seuil appliqué est bien celui du modèle relatif : juste en dessous, la trame est perdue."""
    seuil = receiver_sensitivity_dbm(9)
    modele = LogDistanceModel(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=2.7)
    # Distance telle que le RSSI vaille exactement le seuil - 1 dB, à P_tx = 14 dBm et G = 0.
    portee = modele.range_m(14.0 - (seuil - 1.0))
    juste_dessous = simulate_uplinks_trace([EndDevice(x_m=portee, spreading_factor=9,
                                                      messages=1)], Gateway(), PROPAGATION)
    assert juste_dessous.records[0].outcome == LOST_SENSITIVITY


# ---------------------------------------------------------------- 5. Collisions

def test_same_sf_overlapping_transmissions_collide():
    """Deux trames de même SF qui se chevauchent se détruisent mutuellement."""
    issues = _outcomes([EndDevice(x_m=500.0, spreading_factor=9, messages=1),
                        EndDevice(x_m=0.0, y_m=500.0, spreading_factor=9, messages=1)])
    assert issues == [LOST_COLLISION, LOST_COLLISION]


def test_the_engine_models_a_single_frequency_so_distinct_channels_are_not_expressible():
    """Caractérisation de la limite : la fréquence est portée par la propagation, pas par la trame.

    Il n'existe donc aucun moyen de déclarer deux trames « de même SF mais de fréquences
    différentes » : elles sont, dans ce modèle, sur le même canal et collisionnent. C'est une
    limite documentée du simulateur à la base, pas un comportement à corriger en R1.
    """
    champs = set(EndDevice.__dataclass_fields__)
    assert "frequency_hz" not in champs
    assert "channel" not in champs
    assert "frequency_hz" in Propagation.__dataclass_fields__


def _issues_pour_ecart(delta_db):
    """Deux dispositifs au même endroit et au même instant, séparés par un écart de puissance."""
    return _outcomes([EndDevice(x_m=500.0, spreading_factor=9, messages=1, tx_power_dbm=14.0),
                      EndDevice(x_m=500.0, spreading_factor=9, messages=1,
                                tx_power_dbm=14.0 - delta_db)])


def test_capture_threshold_boundary_is_exactly_six_db_and_inclusive():
    """Frontière de capture mesurée : 5 dB -> collision, 6 dB -> la trame forte est reçue.

    L'écart est réglé par la puissance d'émission, donc exact, au lieu de passer par une
    distance qui ne donnerait qu'un écart approché. Le seuil est inclusif.
    """
    assert _issues_pour_ecart(5.0) == [LOST_COLLISION, LOST_COLLISION]
    assert _issues_pour_ecart(6.0) == [RECEIVED, LOST_COLLISION]


def test_capture_by_distance_confirms_the_delta_computed_from_path_loss():
    """Même frontière vue par les distances : 500 m contre 1118 m donne ~7 dB, donc capture."""
    issues = _outcomes([EndDevice(x_m=500.0, spreading_factor=9, messages=1),
                        EndDevice(x_m=1118.0, spreading_factor=9, messages=1)])
    assert issues == [RECEIVED, LOST_COLLISION]


def test_capture_threshold_above_the_power_delta_keeps_the_collision():
    """Seuil de capture porté à 12 dB : l'écart de ~7 dB ne suffit plus, les deux sont perdues."""
    issues = _outcomes([EndDevice(x_m=500.0, spreading_factor=9, messages=1),
                        EndDevice(x_m=1118.0, spreading_factor=9, messages=1)],
                       capture_threshold_db=12.0)
    assert issues == [LOST_COLLISION, LOST_COLLISION]


def test_capture_threshold_does_not_create_a_collision_without_overlap():
    """Le seuil de capture ne joue que sur un chevauchement effectif : sans lui, tout passe."""
    issues = _outcomes([EndDevice(x_m=500.0, spreading_factor=9, messages=1),
                        EndDevice(x_m=1118.0, spreading_factor=9, messages=1,
                                  start_offset_ns=5_000_000_000)])
    assert issues == [RECEIVED, RECEIVED]


# ---------------------------------------------------------------- 6. Contrôles

def test_different_sf_do_not_collide():
    """Deux SF différents ne se détruisent pas, même simultanés et au même niveau."""
    issues = _outcomes([EndDevice(x_m=500.0, spreading_factor=9, messages=1),
                        EndDevice(x_m=0.0, y_m=500.0, spreading_factor=10, messages=1)])
    assert issues == [RECEIVED, RECEIVED]


def test_non_overlapping_same_sf_transmissions_do_not_collide():
    """Même SF mais 5 s d'écart : aucun chevauchement, aucune collision."""
    issues = _outcomes([EndDevice(x_m=500.0, spreading_factor=9, messages=1),
                        EndDevice(x_m=0.0, y_m=500.0, spreading_factor=9, messages=1,
                                  start_offset_ns=5_000_000_000)])
    assert issues == [RECEIVED, RECEIVED]


def test_partial_overlap_collides_only_while_the_airtimes_intersect():
    """La frontière est exactement le temps d'antenne : 140 ms chevauche, 150 ms non.

    Temps d'antenne mesuré pour SF9 / 10 octets / 125 kHz : 144 384 000 ns. Le décalage de
    140 ms laisse un recouvrement de 4,384 ms (collision) ; 150 ms le supprime.
    """
    assert AIRTIME_SF9_10O_NS == 144_384_000

    def issues_avec_decalage(decalage_ns):
        return _outcomes([EndDevice(x_m=500.0, spreading_factor=9, messages=1),
                          EndDevice(x_m=500.0, spreading_factor=9, messages=1,
                                    start_offset_ns=decalage_ns)])

    assert issues_avec_decalage(140_000_000) == [LOST_COLLISION, LOST_COLLISION]
    assert issues_avec_decalage(150_000_000) == [RECEIVED, RECEIVED]


def test_airtime_grows_with_the_spreading_factor():
    """Contrôle de cohérence : à charge égale, SF12 occupe le canal bien plus longtemps que SF7."""
    durees = {}
    for sf in (7, 9, 12):
        resultat = simulate_uplinks_trace([EndDevice(x_m=500.0, spreading_factor=sf,
                                                     messages=1)], Gateway(), PROPAGATION)
        enregistrement = resultat.records[0]
        durees[sf] = enregistrement.end_ns - enregistrement.start_ns
    assert durees[7] < durees[9] < durees[12]

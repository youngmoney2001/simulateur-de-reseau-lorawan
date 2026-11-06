"""Inventaire validé des commandes MAC disponibles dans le projet.

Le codec vit dans le cœur (`core/src/mac_commands.cpp`) et son pont Python est `lsim.mac`.
Ce fichier ne teste pas la sémantique de chaque commande — `python/tests/test_mac.py` le fait —
mais **la totalité de l'inventaire** : chaque commande déclarée est codable, décodable dans le bon
sens, et retombe sur ses propres champs. Une commande ajoutée sans ligne dans le tableau, ou une
ligne qui ne correspond plus aux champs du codec, fait échouer la suite.

Ce que ce fichier ne dit pas : qu'une commande est *appliquée* par un serveur. LinkADR et
DutyCycle le sont par `lsim.mac_loop` ; les autres restent des codecs (voir
`docs/MAC_CONSOLIDATION.md`, section « Commandes MAC »).
"""

import dataclasses
import inspect

from lsim import mac

#: (classe, arguments représentatifs, sens descendant, CID attendu)
COMMANDES = (
    (mac.LinkCheckReq, {}, False, 0x02),
    (mac.LinkCheckAns, {"margin": 10, "gw_cnt": 1}, True, 0x02),
    (mac.LinkAdrReq, {"data_rate": 3, "tx_power": 4, "ch_mask": 1, "ch_mask_cntl": 0,
                      "nb_trans": 1}, True, 0x03),
    (mac.LinkAdrAns, {"channel_mask_ack": True, "data_rate_ack": True, "power_ack": True},
     False, 0x03),
    (mac.DutyCycleReq, {"max_dcycle": 1}, True, 0x04),
    (mac.DutyCycleAns, {}, False, 0x04),
    (mac.RxParamSetupReq, {"rx2_data_rate": 3, "rx1_dr_offset": 0, "freq_100hz": 8_695_250},
     True, 0x05),
    (mac.RxParamSetupAns, {"channel_ack": True, "rx2_data_rate_ack": True,
                           "rx1_dr_offset_ack": True}, False, 0x05),
    (mac.DevStatusReq, {}, True, 0x06),
    (mac.DevStatusAns, {"battery": 200, "margin": 5}, False, 0x06),
    (mac.NewChannelReq, {"ch_index": 3, "freq_100hz": 8_671_000, "min_dr": 0, "max_dr": 5},
     True, 0x07),
    (mac.NewChannelAns, {"dr_range_ack": True, "channel_freq_ack": True}, False, 0x07),
    (mac.RxTimingSetupReq, {"delay": 1}, True, 0x08),
    (mac.RxTimingSetupAns, {}, False, 0x08),
    (mac.DlChannelReq, {"ch_index": 1, "freq_100hz": 8_695_250}, True, 0x0A),
    (mac.DlChannelAns, {"channel_freq_ok": True, "uplink_freq_exists": True}, False, 0x0A),
    (mac.RekeyInd, {"minor": 1}, False, 0x0B),
    (mac.RekeyConf, {"minor": 1}, True, 0x0B),
    (mac.AdrParamSetupReq, {"limit_exp": 1, "delay_exp": 1}, True, 0x0C),
    (mac.AdrParamSetupAns, {}, False, 0x0C),
    (mac.DeviceTimeReq, {}, False, 0x0D),
    (mac.DeviceTimeAns, {"seconds": 1_000, "fraction": 3}, True, 0x0D),
    (mac.ForceRejoinReq, {"period": 1, "max_retries": 1, "rejoin_type": 0, "dr": 0}, True, 0x0E),
    (mac.RejoinParamSetupReq, {"max_time_n": 1, "max_count_n": 1}, True, 0x0F),
    (mac.RejoinParamSetupAns, {"time_ok": True}, False, 0x0F),
    (mac.PingSlotInfoReq, {"periodicity": 1}, False, 0x10),
    (mac.PingSlotInfoAns, {}, True, 0x10),
    (mac.PingSlotChannelReq, {"freq_100hz": 8_695_250, "dr": 3}, True, 0x11),
    (mac.PingSlotChannelAns, {"channel_freq_ok": True, "data_rate_ok": True}, False, 0x11),
    (mac.BeaconFreqReq, {"freq_100hz": 8_695_250}, True, 0x13),
    (mac.BeaconFreqAns, {"beacon_freq_ok": True}, False, 0x13),
)


def _commandes_du_module():
    return {nom: objet for nom, objet in vars(mac).items()
            if inspect.isclass(objet) and dataclasses.is_dataclass(objet)
            and objet.__module__ == "lsim.mac"}


def test_the_inventory_covers_every_command_of_the_codec():
    """Aucune commande du codec n'est oubliée : l'ensemble déclaré est l'ensemble testé."""
    du_module = set(_commandes_du_module().values())
    testees = {classe for classe, _kw, _dl, _cid in COMMANDES}
    assert testees == du_module
    assert len(testees) == 31, "ajouter une commande exige une ligne dans COMMANDES"


def test_every_command_round_trips_in_its_direction():
    for classe, arguments, descendant, _cid in COMMANDES:
        commande = classe(**arguments)
        octets = mac.encode(commande)
        relue, taille = mac.decode_one(octets, downlink=descendant)
        assert taille == len(octets), classe.__name__
        assert relue == commande, classe.__name__


def test_every_command_declares_the_expected_identifier():
    for classe, arguments, _descendant, cid in COMMANDES:
        octets = mac.encode(classe(**arguments))
        assert octets[0] == cid, (classe.__name__, hex(octets[0]), hex(cid))


def test_the_two_directions_are_distinguished_for_the_shared_identifiers():
    """Le CID 0x02 est LinkCheckReq en montée et LinkCheckAns en descente : le sens compte."""
    montant = mac.encode(mac.LinkCheckReq())
    descendant = mac.encode(mac.LinkCheckAns(margin=0, gw_cnt=1))
    assert montant[0] == descendant[0] == 0x02
    assert isinstance(mac.decode_one(montant, downlink=False)[0], mac.LinkCheckReq)
    assert isinstance(mac.decode_one(descendant, downlink=True)[0], mac.LinkCheckAns)

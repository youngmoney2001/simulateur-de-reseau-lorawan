"""Tests de l inspecteur de trames (module frame_view).

Portent sur la forme de la trame et le determinisme. La conformite cryptographique
est etablie par test_security.py ; frame_view en reutilise les primitives sans les
reimplementer.
"""

from __future__ import annotations

import unittest

from lsim import security
from lsim.frame_view import (MTYPE_NAMES, build_uplink_wire, derive_session, describe,
                             frames_for_run)
from lsim.scenario import load_scenario
from lsim.trace_events import build_trace

EXEMPLE = """
schema_version: 1
name: essai trames
seed: 42
gateway:
  x_m: 0
  y_m: 0
groups:
  - name: capteurs
    count: 3
    placement:
      type: disk
      radius_m: 400
    spreading_factor: 9
    payload_bytes: 8
    tx_power_dbm: 14
    period_s: 600
    messages: 3
"""


def _scenario():
    return load_scenario(EXEMPLE)


class SessionDeterministe(unittest.TestCase):
    def test_meme_graine_meme_trame(self) -> None:
        a = build_uplink_wire(derive_session(42, 1), fcnt32=0, payload=b"AB", fport=1)
        b = build_uplink_wire(derive_session(42, 1), fcnt32=0, payload=b"AB", fport=1)
        self.assertEqual(a, b)

    def test_graine_differente_trame_differente(self) -> None:
        a = build_uplink_wire(derive_session(1, 0), fcnt32=0, payload=b"AB", fport=1)
        b = build_uplink_wire(derive_session(2, 0), fcnt32=0, payload=b"AB", fport=1)
        self.assertNotEqual(a, b)

    def test_deux_dispositifs_devaddr_distincts(self) -> None:
        self.assertNotEqual(derive_session(7, 0).dev_addr, derive_session(7, 1).dev_addr)

    def test_devaddr_tient_sur_32_bits(self) -> None:
        for i in range(20):
            self.assertTrue(0 <= derive_session(99, i).dev_addr <= 0xFFFFFFFF)


class FormeDeLaTrame(unittest.TestCase):
    def setUp(self) -> None:
        self.session = derive_session(42, 3)
        self.wire = build_uplink_wire(self.session, fcnt32=5, payload=b"Z" * 8, fport=2,
                                      confirmed=True, adr=True)
        self.vue = describe(self.wire)
    def test_taille(self) -> None:
        self.assertEqual(len(self.wire), 1 + 7 + 1 + 8 + 4)
    def test_mhdr(self) -> None:
        self.assertEqual(self.vue.mtype_name, "confirmed_data_up")
        s = build_uplink_wire(self.session, fcnt32=0, payload=b"", fport=None)
        self.assertEqual(describe(s).mtype_name, "unconfirmed_data_up")
    def test_major(self) -> None:
        self.assertEqual(self.vue.major_name, "LoRaWAN R1")
    def test_devaddr(self) -> None:
        self.assertEqual(self.vue.dev_addr, self.session.dev_addr)
    def test_fcnt(self) -> None:
        self.assertEqual(self.vue.fcnt, 5)
    def test_adr(self) -> None:
        self.assertTrue(self.vue.adr)
    def test_pas_adr(self) -> None:
        w = build_uplink_wire(self.session, fcnt32=0, payload=b"", fport=None, adr=False)
        self.assertFalse(describe(w).adr)
    def test_fport(self) -> None:
        self.assertEqual(self.vue.fport, 2)
        self.assertEqual(len(self.vue.frm_payload), 8)
    def test_sans_fport(self) -> None:
        w = build_uplink_wire(self.session, fcnt32=0, payload=b"", fport=None)
        self.assertIsNone(describe(w).fport)
        self.assertEqual(len(w), 12)
    def test_mic(self) -> None:
        self.assertEqual(len(self.vue.mic), 4)
        self.assertNotEqual(self.vue.mic, b"\x00\x00\x00\x00")


class ChiffrementParLeCoeur(unittest.TestCase):
    """La charge est chiffree par le coeur C++, pas par ce module."""

    def test_la_charge_claire_n_apparait_pas(self) -> None:
        clair = b"SECRET1234"
        wire = build_uplink_wire(derive_session(5, 5), fcnt32=0, payload=clair, fport=1)
        self.assertNotIn(clair, wire)

    def test_le_coeur_retrouve_la_charge(self) -> None:
        session = derive_session(5, 5)
        clair = b"SECRET1234"
        wire = build_uplink_wire(session, fcnt32=9, payload=clair, fport=1)
        ctx = security.UplinkContext(fcnt32=9, tx_dr=0, tx_ch=0)
        self.assertEqual(security.open_uplink(wire, session.keys, ctx).payload, clair)


class Robustesse(unittest.TestCase):
    def test_trame_trop_courte_refusee(self) -> None:
        with self.assertRaises(ValueError):
            describe(b"\x40\x01\x02")
    def test_type_invalide_refuse(self) -> None:
        with self.assertRaises(ValueError):
            describe("4040")
    def test_fopts_annonces_au_dela_de_la_trame(self) -> None:
        t = bytes([0x40, 1, 2, 3, 4, 0x0F, 0, 0]) + b"\x00" * 4
        with self.assertRaises(ValueError):
            describe(t)
    def test_charge_trop_grande(self) -> None:
        with self.assertRaises(ValueError):
            build_uplink_wire(derive_session(1, 1), fcnt32=0,
                              payload=b"X" * (security.MAX_FRM_PAYLOAD + 1), fport=1)
    def test_charge_sans_fport(self) -> None:
        with self.assertRaises(ValueError):
            build_uplink_wire(derive_session(1, 1), fcnt32=0, payload=b"X", fport=None)


class Presentation(unittest.TestCase):
    def setUp(self) -> None:
        self.vue = describe(build_uplink_wire(derive_session(3, 3), fcnt32=2,
                                              payload=b"AB", fport=1))
    def test_trois_couches(self) -> None:
        self.assertEqual(set(self.vue.couches()), {"phy", "mac", "application"})
    def test_hex_complet(self) -> None:
        self.assertEqual(self.vue.couches()["phy"]["contenu_hex"], self.vue.wire.hex())
    def test_lignes(self) -> None:
        texte = "\n".join(self.vue.lignes())
        for c in ("PHY", "MHDR", "DevAddr", "FCtrl", "FCnt", "FPort", "Charge", "MIC"):
            self.assertIn(c, texte)
    def test_mtypes(self) -> None:
        self.assertEqual(len(MTYPE_NAMES), 8)


class TramesDUneTrace(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sc = _scenario()
        cls.trace = build_trace(cls.sc)
        cls.vues = frames_for_run(cls.trace, cls.sc)

    def test_une_vue_par_evenement(self) -> None:
        self.assertEqual(len(self.vues), len(self.trace.events))

    def test_les_uplinks_portent_une_trame(self) -> None:
        up = [i for i, e in enumerate(self.trace.events) if e.kind == "uplink"]
        self.assertTrue(up)
        for i in up:
            self.assertIsNotNone(self.vues[i])

    def test_la_charge_suit_le_scenario(self) -> None:
        for i, v in enumerate(self.vues):
            if v is not None:
                self.assertEqual(len(v.frm_payload), 8)

    def test_fcnt_croissant_par_dispositif(self) -> None:
        par = {}
        for e, v in zip(self.trace.events, self.vues):
            if v is not None:
                par.setdefault(e.device_index, []).append(v.fcnt)
        for d, suite in par.items():
            self.assertEqual(suite, list(range(len(suite))))

    def test_determinisme_de_bout_en_bout(self) -> None:
        autres = frames_for_run(build_trace(_scenario()), _scenario())
        self.assertEqual(tuple(v.wire if v else None for v in self.vues),
                         tuple(v.wire if v else None for v in autres))

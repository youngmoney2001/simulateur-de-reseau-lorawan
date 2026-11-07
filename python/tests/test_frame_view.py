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

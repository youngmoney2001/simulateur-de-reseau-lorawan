import pytest

from lsim.class_b import (
    BEACON_PERIOD_NS, BEACON_RESERVED_NS, SLOT_NS, SLOTS_PER_WINDOW, BeaconState,
    ClassBDevice, decode_beacon, ping_offset,
)
from lsim.lora import StatusError

EU_BEACON = bytes.fromhex("0000" "000002cc" "a27e" "00" "012000" "008103" "de55")
SEC = 1_000_000_000


def test_beacon_crc_and_time_from_spec_example():
    assert decode_beacon(EU_BEACON) == 0xCC020000
    bad = bytearray(EU_BEACON)
    bad[5] ^= 0x01
    with pytest.raises(StatusError) as e:
        decode_beacon(bytes(bad))
    assert e.value.code == 802


def test_ping_offset_vectors_openssl():
    # Vecteurs calculés hors code avec openssl aes-128-ecb (clé nulle).
    assert ping_offset(0xCC020000, 0x26011234, 0) == 6
    assert ping_offset(0, 0, 7) == 2406
    assert ping_offset(1234567, 0xFFFFFFFF, 2) == 94


def test_state_machine_and_beacon_less_limit():
    d = ClassBDevice(dev_addr=0x26011234, periodicity=7)
    assert d.beacon_state(0) == BeaconState.NOT_SYNCHRONIZED
    with pytest.raises(StatusError) as e:
        d.next_ping_slot(0)
    assert e.value.code == 803
    d = d.on_beacon(1000 * SEC, 500)
    assert d.beacon_state(1060 * SEC) == BeaconState.SYNCHRONIZED
    assert d.beacon_state(1200 * SEC) == BeaconState.BEACON_LESS
    assert d.beacon_state(1000 * SEC + 2 * 3600 * SEC) == BeaconState.LOST
    with pytest.raises(StatusError) as e:
        d.next_ping_slot(1000 * SEC + 2 * 3600 * SEC)
    assert e.value.code == 804
    # Un beacon ramène la classe B.
    d = d.on_beacon(3 * 3600 * SEC, 9999)
    assert d.beacon_state(3 * 3600 * SEC) == BeaconState.SYNCHRONIZED


def test_next_ping_slot_timing_periodicity_7():
    d = ClassBDevice(dev_addr=0, periodicity=7).on_beacon(50 * SEC, 0)
    slot = d.next_ping_slot(50 * SEC)
    assert slot.slot_index == 2406
    assert slot.start_ns == 50 * SEC + 74_300_000_000  # 2,120 s + 2406 × 30 ms après le beacon
    assert slot.beacon_time_s == 0
    nxt = d.next_ping_slot(slot.start_ns + 1)
    assert nxt.beacon_time_s == 128
    assert nxt.slot_index == ping_offset(128, 0, 7)
    assert nxt.beacon_period_start_ns == 50 * SEC + BEACON_PERIOD_NS


def test_slots_stay_inside_window_and_respect_order():
    d = ClassBDevice(dev_addr=0x01020304, periodicity=0).on_beacon(7 * SEC, 123456)
    now = 7 * SEC
    last = 0
    for _ in range(300):
        s = d.next_ping_slot(now)
        assert s.start_ns >= now and s.start_ns >= last
        rel = s.start_ns - s.beacon_period_start_ns
        assert BEACON_RESERVED_NS <= rel and rel + SLOT_NS <= BEACON_PERIOD_NS - 3 * SEC
        assert s.slot_index < SLOTS_PER_WINDOW and s.slot_index % 32 == ping_offset(s.beacon_time_s, 0x01020304, 0) % 32
        last = s.start_ns
        now = s.start_ns + 1


def test_beacon_time_wraps_modulo_2_32():
    d = ClassBDevice(dev_addr=0, periodicity=7).on_beacon(0, 0xFFFFFFFF - 10)
    assert d.next_ping_slot(127 * SEC).beacon_time_s == 117


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        ClassBDevice(dev_addr=0, periodicity=8)
    with pytest.raises(ValueError):
        ClassBDevice(dev_addr=2**32)
    with pytest.raises(ValueError):
        decode_beacon(EU_BEACON, rfu_len=4)
    d = ClassBDevice(dev_addr=0).on_beacon(10 * SEC, 1)
    with pytest.raises(StatusError) as e:
        d.on_beacon(5 * SEC, 2)
    assert e.value.code == 801


# --- Le ping slot qui couvre un instant -----------------------------------------------------
# `next_ping_slot` répond à « quand le réseau peut-il émettre ? ». `ping_slot_at` répond à la
# question du terminal : « est-ce que j'écoute à cet instant ? ». Ce sont les deux moitiés du
# même mécanisme, et la seconde n'existait pas.

def test_the_slot_covering_an_instant_is_the_one_the_engine_announced():
    d = ClassBDevice(dev_addr=0x01020304, periodicity=0).on_beacon(0, 0)
    s = d.next_ping_slot(0)
    # Le début du slot annoncé est couvert, et c'est bien ce slot-là.
    assert d.ping_slot_at(s.start_ns) == s
    assert d.ping_slot_at(s.start_ns + SLOT_NS - 1) == s
    # Hors fenêtre : une nanoseconde avant, et dès la fin du slot (fenêtre demi-ouverte).
    assert d.ping_slot_at(s.start_ns - 1) is None
    assert d.ping_slot_at(s.start_ns + SLOT_NS) is None


def test_drift_widens_the_window_on_both_sides():
    d = ClassBDevice(dev_addr=0x01020304, periodicity=0, clock_drift_ppm=10).on_beacon(0, 0)
    s = d.next_ping_slot(0)
    marge = d.ping_slot_at(s.start_ns).window_half_ns
    assert marge > 0
    assert d.ping_slot_at(s.start_ns - marge) is not None
    assert d.ping_slot_at(s.start_ns - marge - 1) is None
    assert d.ping_slot_at(s.start_ns + SLOT_NS + marge - 1) is not None
    assert d.ping_slot_at(s.start_ns + SLOT_NS + marge) is None


def test_a_device_outside_its_ping_slots_listens_to_nothing():
    # Périodicité 7 : un seul ping slot par période de 128 s. Le terminal y passe donc
    # 30 ms sur 128 s — l'essentiel du temps, il n'écoute pas. C'est la grandeur que
    # n'importe quel bilan de classe B doit pouvoir lire.
    d = ClassBDevice(dev_addr=0x01020304, periodicity=7).on_beacon(0, 0)
    s = d.next_ping_slot(0)
    ouverts = sum(1 for k in range(0, BEACON_PERIOD_NS, 10_000_000)
                  if d.ping_slot_at(k) is not None)
    assert ouverts >= 1
    # 30 ms couvertes par pas de 10 ms : 3 ou 4 échantillons, pas davantage.
    assert ouverts <= 6, ouverts
    assert d.ping_slot_at(s.start_ns) is not None


def test_without_a_beacon_there_is_no_ping_slot():
    d = ClassBDevice(dev_addr=0x01020304, periodicity=0)
    with pytest.raises(StatusError) as e:
        d.ping_slot_at(10 * SEC)
    assert e.value.code == 803          # NotSynchronized
    # 2 h sans balise : la classe B est quittée.
    d = d.on_beacon(0, 0)
    with pytest.raises(StatusError) as e:
        d.ping_slot_at(120 * 60 * SEC)
    assert e.value.code == 804          # BeaconLost

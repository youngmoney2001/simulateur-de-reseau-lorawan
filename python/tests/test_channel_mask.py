"""Sous-bandes et masques LinkADRReq (US915, AU915) : règle RP002, rejets, liaison scénario."""

import pytest

from lsim.channel_mask import (
    all_channels,
    apply_link_adr,
    link_adr_for_sub_band,
    sub_band_channels,
    sub_band_of,
)

NONE = frozenset()


def test_sub_band_1_and_8_contents():
    assert sub_band_channels(1) == frozenset(range(0, 8)) | {64}
    assert sub_band_channels(8) == frozenset(range(56, 64)) | {71}


def test_sub_band_partition_covers_all_channels_once():
    seen = []
    for n in range(1, 9):
        seen.extend(sorted(sub_band_channels(n)))
    assert sorted(seen) == list(range(72))


def test_sub_band_of_matches_membership():
    for channel in range(72):
        assert channel in sub_band_channels(sub_band_of(channel))
    assert sub_band_of(72) is None


def test_sub_band_out_of_range_refused():
    for bad in (0, 9, True, "2"):
        with pytest.raises(ValueError):
            sub_band_channels(bad)


def test_link_adr_for_sub_band_selects_exactly_that_band():
    for n in range(1, 9):
        mask, cntl = link_adr_for_sub_band(n)
        assert cntl == 5
        assert apply_link_adr("US915", all_channels(), mask, cntl) == sub_band_channels(n)
        assert apply_link_adr("AU915", all_channels(), mask, cntl) == sub_band_channels(n)


def test_cntl_0_to_3_block_bits_are_individual():
    # Bloc 0 (canaux 0-15) : bits 0 et 2 activés, les autres du bloc désactivés ; reste inchangé.
    result = apply_link_adr("US915", frozenset({40}), 0x0005, 0)
    assert result == frozenset({0, 2, 40})
    # Bloc 3 (canaux 48-63) : ChMask 0x8000 active le canal 63.
    assert apply_link_adr("US915", all_channels(), 0x8000, 3) >= {63}


def test_cntl_4_applies_to_500khz_channels_only():
    assert apply_link_adr("US915", frozenset({0}), 0x0005, 4) == frozenset({0, 64, 66})


def test_cntl_6_enables_all_125khz_and_applies_mask_to_500khz():
    result = apply_link_adr("US915", NONE, 0x01, 6)
    assert result == frozenset(range(0, 64)) | {64}


def test_cntl_7_disables_all_125khz_and_applies_mask_to_500khz():
    result = apply_link_adr("AU915", all_channels(), 0x80, 7)
    assert result == frozenset({71})


def test_rfu_bits_refused():
    with pytest.raises(ValueError):
        apply_link_adr("US915", all_channels(), 0x0100, 5)     # bits 8-15 RFU pour cntl 5
    with pytest.raises(ValueError):
        apply_link_adr("US915", all_channels(), 0x0100, 4)     # bits 8-15 hors bloc 500 kHz
    with pytest.raises(ValueError):
        apply_link_adr("US915", all_channels(), 0x0100, 7)


def test_empty_result_refused():
    # Tout désactivé : l'appareil doit répondre ChMaskAck = 0.
    with pytest.raises(ValueError):
        apply_link_adr("US915", all_channels(), 0x0000, 7)


def test_invalid_fields_refused():
    with pytest.raises(ValueError):
        apply_link_adr("US915", all_channels(), 0x10000, 0)
    with pytest.raises(ValueError):
        apply_link_adr("US915", all_channels(), 0x0001, 8)
    with pytest.raises(ValueError):
        apply_link_adr("US915", all_channels(), 0x0001, 2.0)
    with pytest.raises(ValueError):
        apply_link_adr("US915", frozenset({72}), 0x0001, 0)


def test_other_plans_refused():
    with pytest.raises(ValueError):
        apply_link_adr("EU868", all_channels(), 0x0001, 0)
    with pytest.raises(ValueError):
        sub_band_channels(0)


# -------------------------------------------- liaison scénario -> sous-bande

def _group(**kw):
    from lsim.scenario import DiskPlacement, GroupModel
    base = dict(name="g", count=1, placement=DiskPlacement(type="disk", radius_m=10))
    base.update(kw)
    return GroupModel(**base)


def test_scenario_sub_band_accepts_channel_inside_band():
    # Sous-bande 2 : canal 8 à 903,9 MHz (125 kHz).
    g = _group(region="US915", channel_freq_hz=903_900_000, sub_band=2)
    assert g.sub_band == 2


def test_scenario_sub_band_accepts_500khz_channel_of_band():
    # Sous-bande 2 : canal 500 kHz 65 à 904,6 MHz.
    _group(region="US915", channel_freq_hz=904_600_000, sub_band=2)


def test_scenario_sub_band_refuses_channel_outside_band():
    with pytest.raises(ValueError):
        _group(region="US915", channel_freq_hz=902_300_000, sub_band=2)   # canal 0, sous-bande 1


def test_scenario_sub_band_requires_us_or_au_region():
    with pytest.raises(ValueError):
        _group(sub_band=1)
    with pytest.raises(ValueError):
        _group(region="EU868", channel_freq_hz=868_100_000, sub_band=1)


def test_scenario_sub_band_bounds():
    with pytest.raises(ValueError):
        _group(region="US915", channel_freq_hz=902_300_000, sub_band=9)

"""ADR serveur : valeurs calculées à la main, cohérentes avec core/tests/test_adr.cpp."""

import pytest

from lsim.adr import decide
from lsim.lora import StatusError

EU_SF = [12, 11, 10, 9, 8, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]


def _call(snr, **kw):
    args = dict(dr=0, dr_sf=EU_SF, min_dr=0, max_dr=5, tx_power_index=0,
                max_tx_power_index=7, power_step_db=2.0, installation_margin_db=10.0)
    args.update(kw)
    return decide(snr, **args)


def test_strong_link_climbs_to_dr5_and_lowers_power_to_3():
    # SNR max 10 dB : marge 20 dB à SF12, 7,5 dB à SF7 ; puis 3 pas de 2 dB.
    d = _call([10.0] * 20)
    assert (d.dr, d.tx_power_index) == (5, 3)
    assert d.changed_from(0, 0)


def test_uses_max_of_history():
    d = _call([-20.0] * 19 + [10.0])
    assert (d.dr, d.tx_power_index) == (5, 3)


def test_negative_margin_raises_power_only():
    d = _call([-11.0] * 20, tx_power_index=3)
    assert (d.dr, d.tx_power_index) == (0, 2)


def test_hopeless_link_unchanged_at_max_power():
    d = _call([-20.0] * 20)
    assert (d.dr, d.tx_power_index) == (0, 0)
    assert not d.changed_from(0, 0)


def test_power_capped_by_region_maximum():
    d = _call([10.0] * 20, tx_power_index=7)
    assert (d.dr, d.tx_power_index) == (5, 7)


def test_invalid_inputs_are_refused():
    with pytest.raises(ValueError):
        _call([])
    with pytest.raises(ValueError):
        _call([0.0] * 21)
    with pytest.raises(ValueError):
        _call([0.0], dr_sf=[12] * 15)
    with pytest.raises(ValueError):
        _call([0.0], dr=6)  # hors min..max
    with pytest.raises(ValueError):
        _call([0.0], dr_sf=[13] + EU_SF[1:])  # SF 13 : refusé par Python (0..12)
    with pytest.raises(StatusError) as e:
        _call([0.0], power_step_db=0.0)  # refusé par le cœur
    assert e.value.code == 761
    with pytest.raises(StatusError) as e:
        _call([60.0])  # SNR hors -50..50 dB
    assert e.value.code == 761


def test_device_backoff_sequence_matches_normative_steps():
    from lsim.adr import DeviceAdrState, device_downlink, device_uplink

    st = DeviceAdrState(dr=2, min_dr=0, tx_power_index=2, default_tx_power_index=0, channels_subset=True)
    for _ in range(31):
        r = device_uplink(st, limit_exp=5, delay_exp=5)
        st = r.state
        assert not r.ack_req
    r = device_uplink(st, limit_exp=5, delay_exp=5)  # cnt 32 = LIMIT
    st = r.state
    assert r.ack_req and st.tx_power_index == 2
    while st.ack_cnt < 64:
        st = device_uplink(st, limit_exp=5, delay_exp=5).state
    assert st.tx_power_index == 0 and st.dr == 2  # cnt 64 = LIMIT + DELAY : puissance au défaut
    while st.ack_cnt < 96:
        st = device_uplink(st, limit_exp=5, delay_exp=5).state
    assert st.dr == 1
    while st.ack_cnt < 128:
        st = device_uplink(st, limit_exp=5, delay_exp=5).state
    assert st.dr == 0 and not st.channels_subset  # débit minimal : canaux par défaut
    r = device_uplink(st, limit_exp=5, delay_exp=5)
    assert not r.ack_req
    st = device_downlink(r.state)
    assert st.ack_cnt == 0


def test_device_state_validation():
    from lsim.adr import DeviceAdrState, device_uplink

    with pytest.raises(ValueError):
        device_uplink(DeviceAdrState(), limit_exp=16, delay_exp=0)
    with pytest.raises(ValueError):
        device_uplink(DeviceAdrState(dr=16), limit_exp=0, delay_exp=0)
    with pytest.raises(StatusError) as e:
        device_uplink(DeviceAdrState(dr=0, min_dr=1), limit_exp=0, delay_exp=0)
    assert e.value.code == 761


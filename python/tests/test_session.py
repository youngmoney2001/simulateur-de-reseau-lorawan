import pytest

from lsim.lora import StatusError
from lsim.session import DeviceSession, SessionKeys, SessionState

KEYS = SessionKeys(
    f_nwk_s_int_key=bytes([0x11]) * 16,
    s_nwk_s_int_key=bytes([0x22]) * 16,
    nwk_s_enc_key=bytes([0x33]) * 16,
    app_s_key=bytes([0x44]) * 16,
)
JOIN = dict(dev_addr=0x26011234, dr=2, min_dr=0, tx_power_index=1, default_tx_power_index=1)


def test_keys_not_in_repr():
    text = repr(KEYS)
    assert "app_s_key" not in text and "\\x44" not in text


def test_no_session_before_join():
    with DeviceSession() as s:
        assert s.snapshot().state == SessionState.NO_SESSION
        with pytest.raises(StatusError) as e:
            s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
        assert e.value.code == 781


def test_join_then_rekey_conf_then_counters():
    with DeviceSession() as s:
        s.join_accepted(KEYS, **JOIN)
        plan = s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
        assert plan.fcnt32 == 0 and plan.rekey_ind
        s.receive_downlink(fcnt32=0, uses_nf=True, conf_received=True, server_version=1)
        assert s.end_uplink() == SessionState.ACTIVE
        plan = s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
        assert plan.fcnt32 == 1 and not plan.rekey_ind
        with pytest.raises(StatusError) as e:
            s.receive_downlink(fcnt32=0, uses_nf=True)  # NFCntDown déjà consommé
        assert e.value.code == 783
        s.receive_downlink(fcnt32=0, uses_nf=False)  # AFCntDown indépendant
        s.end_uplink()
        snap = s.snapshot()
        assert snap.fcnt_up == 2 and snap.nf_cnt_dwn == 1 and snap.af_cnt_dwn == 1
        assert snap.dev_addr == JOIN["dev_addr"] and not snap.cycle_open


def test_needs_join_after_rekey_timeout_and_rejoin_resets_counters():
    with DeviceSession() as s:
        s.join_accepted(KEYS, **JOIN)
        s.begin_uplink(adr_ack_limit_exp=1, adr_ack_delay_exp=1)
        s.end_uplink()
        s.begin_uplink(adr_ack_limit_exp=1, adr_ack_delay_exp=1)
        assert s.end_uplink() == SessionState.NEEDS_JOIN
        with pytest.raises(StatusError) as e:
            s.begin_uplink(adr_ack_limit_exp=1, adr_ack_delay_exp=1)
        assert e.value.code == 781
        s.join_accepted(KEYS, **JOIN)
        snap = s.snapshot()
        assert snap.state == SessionState.ACTIVE and snap.fcnt_up == 0


def test_cycle_order_and_invalid_parameters():
    with DeviceSession() as s:
        s.join_accepted(KEYS, **JOIN)
        with pytest.raises(ValueError):
            s.begin_uplink(adr_ack_limit_exp=16, adr_ack_delay_exp=0)
        s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
        with pytest.raises(StatusError) as e:
            s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
        assert e.value.code == 782
        s.end_uplink()
        with pytest.raises(StatusError) as e:
            s.end_uplink()
        assert e.value.code == 782


def test_ack_req_reset_by_downlink():
    with DeviceSession() as s:
        s.join_accepted(KEYS, **JOIN)
        s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
        s.receive_downlink(fcnt32=0, conf_received=True, server_version=1)
        s.end_uplink()
        seen = False
        for _ in range(20):
            plan = s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
            s.end_uplink()
            if plan.ack_req:
                seen = True
                break
        assert seen
        s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
        s.receive_downlink(fcnt32=1)
        s.end_uplink()
        plan = s.begin_uplink(adr_ack_limit_exp=3, adr_ack_delay_exp=3)
        assert not plan.ack_req
        s.end_uplink()


def test_closed_handle_and_bad_inputs():
    s = DeviceSession()
    s.close()
    with pytest.raises(StatusError) as e:
        s.snapshot()
    assert e.value.code == 786
    with DeviceSession() as t:
        with pytest.raises(ValueError):
            t.join_accepted(KEYS, dev_addr=2**32, dr=0, min_dr=0, tx_power_index=0,
                            default_tx_power_index=0)
        with pytest.raises(ValueError):
            SessionKeys(b"\x00" * 15, b"\x00" * 16, b"\x00" * 16, b"\x00" * 16)

"""Rekey : machines d'état dispositif et serveur (valeurs de core/tests/test_rekey.cpp)."""

import pytest

from lsim import rekey
from lsim.lora import StatusError


def test_device_reverts_to_join_without_rekey_conf():
    d = rekey.device_join_accepted(rekey.DeviceRekey())
    assert rekey.device_must_send_rekey_ind(d)
    for _ in range(3):
        d = rekey.device_uplink_completed(d, admin_limit=3)
    assert d.state == rekey.DeviceRekeyState.NEEDS_JOIN
    assert not rekey.device_must_send_rekey_ind(d)


def test_device_confirms_only_with_valid_version():
    d = rekey.device_join_accepted(rekey.DeviceRekey())
    d = rekey.device_uplink_completed(d, admin_limit=64, conf_received=True, server_version=0)
    assert d.state == rekey.DeviceRekeyState.PENDING
    d = rekey.device_uplink_completed(d, admin_limit=64, conf_received=True, server_version=2)
    assert d.state == rekey.DeviceRekeyState.PENDING
    d = rekey.device_uplink_completed(d, admin_limit=64, conf_received=True, server_version=1)
    assert d.state == rekey.DeviceRekeyState.CONFIRMED
    assert not rekey.device_must_send_rekey_ind(d)


def test_server_discards_new_context_before_first_rekey_ind():
    s = rekey.server_join_accepted(rekey.ServerRekey())
    s, a = rekey.server_on_uplink(s, new_context=True, has_rekey_ind=False)
    assert a == rekey.ServerAction.DISCARD
    s, a = rekey.server_on_uplink(s, new_context=True, has_rekey_ind=True)
    assert a == rekey.ServerAction.ACCEPT_AND_CONFIRM
    s, a = rekey.server_on_uplink(s, new_context=True, has_rekey_ind=True)
    assert a == rekey.ServerAction.ACCEPT
    s, a = rekey.server_on_uplink(rekey.ServerRekey(awaiting=True), new_context=False, has_rekey_ind=False)
    assert a == rekey.ServerAction.ACCEPT


def test_invalid_arguments():
    with pytest.raises(ValueError):
        rekey.device_uplink_completed(rekey.DeviceRekey(), admin_limit=0)
    with pytest.raises(ValueError):
        rekey.device_uplink_completed(rekey.DeviceRekey(), admin_limit=1, server_version=256)

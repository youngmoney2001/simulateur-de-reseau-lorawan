"""LR-FHSS (US915 et AU915, DR5/DR6) n'est pas géré par le serveur : les uplinks sont refusés.

Ces tests figent ce refus, pour qu'une future prise en charge soit un choix explicite.
"""

import base64
import json

import pytest

from lsim import gwmp
from lsim.gwmp import ProtocolError, Rxpk
from lsim.gwmp_server import JoinUplinkHandler
from lsim.plan import get_plan

EUI = bytes.fromhex("aabbccddeeff0011")
TOKEN = b"\x12\x34"


@pytest.mark.parametrize("dr", [5, 6])
def test_us915_lrfhss_data_rates_are_outside_the_plan(dr):
    # US915 DR5 et DR6 = LR-FHSS (uplink seulement) : hors plan.
    with pytest.raises(ValueError):
        get_plan("US915").dr_datr(dr)


def test_au915_has_no_lrfhss_modulation_in_plan():
    # AU915 DR5 et DR6 sont des débits LoRa (SF7/125 et SF8/500) : ils restent gérés.
    plan = get_plan("AU915")
    assert plan.dr_datr(5) == "SF7BW125" and plan.dr_datr(6) == "SF8BW500"
    with pytest.raises(ValueError):
        plan.data_rate_index("LRFHSS")


@pytest.mark.parametrize("region", ["US915", "AU915"])
def test_lrfhss_modulation_is_not_parsed(region):
    rxpk = {"tmst": 1, "chan": 0, "rfch": 0, "freq": 915.2, "stat": 1,
            "modu": "LRFHSS", "datr": "1523", "codr": "1/3", "rssi": -40, "lsnr": 5.0,
            "size": 4, "data": base64.b64encode(b"\x01\x02\x03\x04").decode()}
    body = json.dumps({"rxpk": [rxpk]}).encode()
    wire = gwmp.build_push_data(TOKEN, EUI, [])[:12] + body
    with pytest.raises(ProtocolError):
        gwmp.parse_upstream(wire)


@pytest.mark.parametrize("region", ["US915", "AU915"])
def test_join_request_on_lrfhss_is_not_accepted(region):
    handler = JoinUplinkHandler(join_server=None, plan=get_plan(region))
    rx = Rxpk(tmst=1, freq_mhz=915.2, chan=0, rfch=0, crc_ok=True, datr="LRFHSS",
              codr="1/3", rssi=-40, lsnr=5.0, payload=b"\x00" * 23)
    outcome = handler.handle(rx)
    assert outcome.issue == "join_unsupported_channel"
    assert outcome.txpk is None

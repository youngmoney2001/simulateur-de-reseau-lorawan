"""Commande `lsim serve` : fichier de clés, secrets, erreurs de configuration."""

import json
import os

import pytest

from lsim.__main__ import main
from lsim.plan import get_plan
from lsim.serve import DATA_ENV, INTEGRITY_ENV, load_keys_file

DEV = "0102030405060708"
NWK = "10" * 16


def _write_keys(path, doc, mode=0o600):
    path.write_text(json.dumps(doc), encoding="utf-8")
    os.chmod(path, mode)
    return path


def test_keys_file_loaded(tmp_path):
    p = _write_keys(tmp_path / "keys.json", {"devices": {DEV: {"nwk_key": NWK}}})
    table = load_keys_file(p)
    # DevEUI écrit en ordre d'affichage TTN ; stocké en ordre de transmission (inverse).
    assert table[bytes.fromhex(DEV)[::-1]].nwk_key == bytes.fromhex(NWK)
    assert bytes.fromhex(DEV) not in table


def test_world_or_group_readable_keys_refused(tmp_path):
    p = _write_keys(tmp_path / "keys.json", {"devices": {DEV: {"nwk_key": NWK}}}, mode=0o644)
    with pytest.raises(ValueError, match="chmod 600"):
        load_keys_file(p)


@pytest.mark.parametrize("doc", [
    {"devices": {"0102": {"nwk_key": NWK}}},          # DevEUI trop court
    {"devices": {DEV: {"nwk_key": "zz" * 16}}},       # hexadécimal invalide
    {"devices": {DEV: {}}},                           # clé absente
    {"devices": []},                                  # mauvais type
    [],                                               # racine non objet
])
def test_invalid_keys_file_refused(tmp_path, doc):
    p = _write_keys(tmp_path / "keys.json", doc)
    with pytest.raises(ValueError):
        load_keys_file(p)


def test_serve_refuses_without_integrity_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(INTEGRITY_ENV, raising=False)
    p = _write_keys(tmp_path / "keys.json", {"devices": {DEV: {"nwk_key": NWK}}})
    rc = main(["serve", "--db", str(tmp_path / "j.sqlite"), "--keys", str(p)])
    assert rc == 2
    assert INTEGRITY_ENV in capsys.readouterr().err


def test_serve_refuses_bad_net_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(INTEGRITY_ENV, "00" * 16)
    monkeypatch.setenv(DATA_ENV, "11" * 32)
    p = _write_keys(tmp_path / "keys.json", {"devices": {DEV: {"nwk_key": NWK}}})
    rc = main(["serve", "--db", str(tmp_path / "j.sqlite"), "--keys", str(p), "--net-id", "13"])
    assert rc == 2


def test_net_id_is_sent_little_endian(tmp_path, monkeypatch):
    from lsim import serve
    monkeypatch.setenv(INTEGRITY_ENV, "00" * 16)
    monkeypatch.setenv(DATA_ENV, "11" * 32)
    captured = {}

    def fake_build(db, keys, net_id, plan):
        captured["net_id"] = net_id
        raise SystemExit(0)
    monkeypatch.setattr(serve, "build_handler", fake_build)
    p = _write_keys(tmp_path / "keys.json", {"devices": {DEV: {"nwk_key": NWK}}})
    with pytest.raises(SystemExit):
        serve.run("127.0.0.1", 1, tmp_path / "j.sqlite", p, "000013")
    assert captured["net_id"] == bytes([0x13, 0x00, 0x00])


def test_display_order_keys_file_joins_end_to_end(tmp_path):
    """keys.json en ordre d'affichage TTN : la jointure reçue (ordre de transmission) la retrouve."""
    from lsim.gwmp import Rxpk
    from lsim.security import JoinRequest, encode_join_request
    from lsim.serve import build_handler, load_keys_file
    from lsim.join_store import DurableJoinStore

    dev_eui = bytes.fromhex("0102030405060708")          # ordre de transmission
    display = dev_eui[::-1].hex()                        # 0807060504030201, comme TTN
    nwk = bytes(range(0x10, 0x20))
    join_eui = bytes.fromhex("1122334455667788")
    keys_path = tmp_path / "keys.json"
    keys_path.write_text(
        '{"devices": {"%s": {"nwk_key": "%s"}}}' % (display, nwk.hex()), encoding="utf-8")
    keys_path.chmod(0o600)
    store = DurableJoinStore(tmp_path / "join.sqlite", bytes(range(16)), bytes(range(0x80, 0xA0)))
    handler = build_handler(store, load_keys_file(keys_path), bytes([0x13, 0, 0]), get_plan("EU868"))
    wire = encode_join_request(JoinRequest(join_eui, dev_eui, (1).to_bytes(2, "little")), nwk)
    outcome = handler.handle(Rxpk(tmst=1_000_000, freq_mhz=868.1, chan=0, rfch=0, crc_ok=True,
                                  datr="SF7BW125", codr="4/5", rssi=-60, lsnr=7.0, payload=wire))
    assert outcome.issue == "join_accepted"


"""Commande `lsim serve` : fichier de clés, secrets, erreurs de configuration."""

import json
import os

import pytest

from lsim.__main__ import main
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
    assert table[bytes.fromhex(DEV)].nwk_key == bytes.fromhex(NWK)


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

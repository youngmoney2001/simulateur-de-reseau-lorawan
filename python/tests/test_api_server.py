"""Serveur de l'API v1 : jetons, routes, runs, pagination, refus et bornes (`lsim.api_server`).

Le serveur tourne sur une adresse locale, en fil, pour chaque test ; les réponses sont validées
contre les modèles du contrat (`lsim.api_contract`).
"""

import contextlib
import http.client
import json
import os
import shutil
import stat
import threading
import time
from pathlib import Path

import pytest

from lsim import api_server as srv
from lsim.api_contract import (
    ApiScenario, DevicePage, RegionList, RunStatus, RunSummary, TerrainList, TracePage,
    ValidateResponse,
)
from lsim.environment import load_dem_csv
from lsim.export import run_scenario

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
SCHEMAS = ROOT / "schemas" / "api" / "v1"


def _scenario(count=30, messages=4, **extra):
    d = {
        "schema_version": 1,
        "name": "test api",
        "seed": 7,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
        "groups": [{
            "name": "c", "count": count,
            "placement": {"type": "disk", "radius_m": 2500},
            "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14,
            "period_s": 900, "messages": messages, "start_spread_s": 900,
        }],
    }
    d.update(extra)
    return d


@contextlib.contextmanager
def _make_api(tmp_path, terrain_dir=None):
    tokens = tmp_path / "tokens.json"
    store = srv.TokenStore(tokens)
    alice = store.issue("alice")
    bob = store.issue("bob")
    server = srv.make_server("127.0.0.1", 0, tokens, terrain_dir=terrain_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def call(method, path, body=None, token=alice, raw=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        h = {"Content-Type": "application/json"} if body is not None or raw is not None else {}
        if token is not None:
            h["Authorization"] = "Bearer " + token
        h.update(headers or {})
        payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
        conn.request(method, path, body=payload, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        parsed = json.loads(data) if data and resp.getheader("Content-Type", "").startswith(
            "application/json") else None
        return resp.status, parsed

    class Api:
        pass

    api = Api()
    api.call, api.alice, api.bob, api.tokens_path, api.store = call, alice, bob, tokens, store
    api.service = server.service
    try:
        yield api
    finally:
        server.shutdown()
        server.server_close()
        server.service.close()


@pytest.fixture()
def api(tmp_path):
    with _make_api(tmp_path) as a:
        yield a


@pytest.fixture()
def api_relief(tmp_path):
    """Serveur avec un catalogue de reliefs : `quartier.csv` valide, un nom d'identifiant invalide."""
    catalog = tmp_path / "terrains"
    catalog.mkdir()
    shutil.copy(EXAMPLES / "relief_quartier_dem.csv", catalog / "quartier.csv")
    (catalog / "Mauvais Nom.csv").write_text("x_m,y_m,z_m\n", encoding="utf-8")
    with _make_api(tmp_path, terrain_dir=catalog) as a:
        yield a


def _wait_done(api, run_id, token=None, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = api.call("GET", f"/api/v1/runs/{run_id}", token=token or api.alice)
        assert status == 200
        if body["state"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError("run non terminé")


# --- Jetons ------------------------------------------------------------------------------------

def test_token_file_holds_only_hashes_and_is_private(api):
    text = api.tokens_path.read_text(encoding="utf-8")
    assert api.alice not in text and api.bob not in text
    assert "sha256" in text
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(api.tokens_path).st_mode) & 0o077 == 0


def test_missing_or_wrong_token_is_401_without_detail(api):
    for token in (None, "faux", api.alice + "x"):
        status, body = api.call("GET", "/api/v1/regions", token=token)
        assert status == 401 and body["code"] == "unauthorized"
        assert "alice" not in json.dumps(body)


def test_health_needs_no_token(api):
    status, body = api.call("GET", "/api/v1/health", token=None)
    assert status == 200 and body == {"status": "ok", "api_version": "v1"}


def test_revoked_and_expired_tokens_are_refused(api):
    assert api.store.revoke("alice") == 1
    assert api.call("GET", "/api/v1/regions", token=api.alice)[0] == 401
    expired = api.store.issue("carole", expires_at=int(time.time()) - 10)
    assert api.store.resolve(expired) is None
    valid = api.store.issue("dan", expires_at=int(time.time()) + 3600)
    assert api.store.resolve(valid) == "dan"


def test_owner_name_is_restricted(api):
    with pytest.raises(ValueError):
        api.store.issue("../etc")


# --- Routes sans calcul -----------------------------------------------------------------------

def test_regions_match_contract(api):
    status, body = api.call("GET", "/api/v1/regions")
    assert status == 200
    RegionList.model_validate(body)
    assert {r["name"] for r in body["regions"]} >= {"EU868", "US915"}


def test_validate_accepts_and_reports_problems(api):
    status, body = api.call("POST", "/api/v1/scenarios/validate", {"scenario": _scenario()})
    assert status == 200 and body["valid"] is True
    assert len(body["scenario_sha256"]) == 64
    ValidateResponse.model_validate(body)

    bad = _scenario(count=0)
    status, body = api.call("POST", "/api/v1/scenarios/validate", {"scenario": bad})
    assert status == 200 and body["valid"] is False
    assert body["problems"][0]["code"] == "validation_error"


def test_terrain_path_in_scenario_is_refused_with_its_code(api):
    d = _scenario(environment={"terrain": {"type": "dem_csv", "path": "relief.csv"}})
    status, body = api.call("POST", "/api/v1/runs", {"scenario": d})
    assert status == 422 and body["code"] == "terrain_not_allowed"
    status, body = api.call("POST", "/api/v1/scenarios/validate", {"scenario": d})
    assert body["problems"][0]["code"] == "terrain_not_allowed"


def test_mesh_without_profile_is_refused_by_the_scenario_rules(api):
    d = _scenario()
    d.pop("gateway")
    d["gateways"] = [{"name": "a", "x_m": 0, "y_m": 0}, {"name": "b", "x_m": 500, "y_m": 0}]
    d["mesh"] = {"border": "a"}
    status, body = api.call("POST", "/api/v1/runs", {"scenario": d})
    assert status == 422 and "mesh" in body["message"]


def test_mesh_downlink_options_are_refused_explicitly(api):
    d = _mesh_scenario()
    for protocol in ({"confirmed_uplinks": True}, {"downlink_every": 1}, {"join": True}):
        status, body = api.call("POST", "/api/v1/runs", {"scenario": d, "protocol": protocol})
        assert status == 422 and body["code"] == "validation_error", protocol
        assert "mesh" in body["message"]


def _mesh_scenario(count=40):
    d = _scenario(count=count, messages=4)
    d.pop("gateway")
    d["gateways"] = [
        {"name": "frontiere", "x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15,
         "profile": "rak5148", "mesh": True},
        {"name": "relais", "x_m": 1200, "y_m": 0, "antenna_gain_dbi": 2.15,
         "profile": "rak5148", "mesh": True},
        {"name": "ip", "x_m": -2500, "y_m": 0, "antenna_gain_dbi": 2.15},
    ]
    d["mesh"] = {"border": "frontiere", "spreading_factor": 12, "bandwidth_khz": 203,
                 "coding_rate": 1, "payload_bytes": 32, "capture_db": 6, "max_hops": 8}
    return d


def test_mesh_run_reports_totals_and_per_device_losses(api):
    # L'exemple du dépôt, SF12 sur le mesh : des trames décodées sont perdues sur le relais.
    import yaml
    example = Path(__file__).resolve().parents[2] / "examples" / "mesh_relais_quartier.yaml"
    d = yaml.safe_load(example.read_text(encoding="utf-8"))
    d["mesh"]["spreading_factor"] = 12
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d})
    assert status == 202
    rid = created["run_id"]
    assert _wait_done(api, rid)["state"] == "done"
    _, summary = api.call("GET", f"/api/v1/runs/{rid}/summary")
    RunSummary.model_validate(summary)
    t = summary["totals"]
    assert t["sent"] == t["received"] + t["lost_sensitivity"] + t["lost_collision"] \
        + t["lost_gateway_busy"] + t.get("lost_mesh", 0)
    assert t.get("lost_mesh", 0) > 0  # SF12 sur le mesh : pertes réelles
    _, devices = api.call("GET", f"/api/v1/runs/{rid}/devices?limit=500")
    items = devices["items"]
    assert sum(x["received"] for x in items) == t["received"]
    assert sum(x.get("lost_mesh", 0) for x in items) == t["lost_mesh"]
    _, page = api.call("GET", f"/api/v1/runs/{rid}/events?limit=500")
    kinds = {e["kind"] for e in page["items"]}
    assert "mesh_hop" in kinds


def test_unknown_route_and_bad_run_id_are_404(api):
    assert api.call("GET", "/api/v1/absent")[0] == 404
    assert api.call("GET", "/api/v1/runs/..%2Fsecret")[0] == 404
    assert api.call("GET", "/api/v1/runs/trop-court")[0] == 404


def test_body_limits_and_bad_json(api):
    big = "x" * (srv.MAX_BODY_BYTES + 1)
    status, body = api.call("POST", "/api/v1/scenarios/validate", raw=big)
    assert status == 413 and body["code"] == "limit_exceeded"
    status, body = api.call("POST", "/api/v1/scenarios/validate", raw="{pas du json")
    assert status == 422 and body["code"] == "validation_error"
    status, body = api.call("POST", "/api/v1/scenarios/validate", raw="[1, 2]")
    assert status == 422


def test_non_finite_json_constants_are_refused(api):
    status, body = api.call("POST", "/api/v1/scenarios/validate", raw='{"scenario": NaN}')
    assert status == 422


def test_page_parameters_are_checked(api):
    status, body = api.call("POST", "/api/v1/runs", {"scenario": _scenario()})
    run_id = body["run_id"]
    _wait_done(api, run_id)
    for q in ("limit=0", "limit=501", "cursor=-1", "cursor=abc"):
        status, body = api.call("GET", f"/api/v1/runs/{run_id}/events?{q}")
        assert status == 422, q


# --- Runs -------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def finished_run(request):
    """Un run terminé, partagé par les tests de lecture (même moteur, une seule simulation)."""
    tmp = request.getfixturevalue("tmp_path_factory").mktemp("api")
    tokens = tmp / "tokens.json"
    store = srv.TokenStore(tokens)
    token = store.issue("alice")
    server = srv.make_server("127.0.0.1", 0, tokens)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(method, path, body=None, token=token):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        h = {"Authorization": "Bearer " + token}
        if body is not None:
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, (json.loads(data) if data else None)

    status, body = call("POST", "/api/v1/runs", {
        "scenario": _scenario(count=30, messages=4),
        "protocol": {"join": True, "confirmed_uplinks": True, "downlink_every": 2},
    })
    assert status == 202
    run_id = body["run_id"]
    deadline = time.time() + 180
    while time.time() < deadline:
        _, st = call("GET", f"/api/v1/runs/{run_id}")
        if st["state"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert st["state"] == "done", st
    yield {"call": call, "run_id": run_id, "token": token, "store": store}
    server.shutdown()
    server.server_close()
    server.service.close()


def test_run_status_and_summary_follow_the_contract(finished_run):
    call, rid = finished_run["call"], finished_run["run_id"]
    status, body = call("GET", f"/api/v1/runs/{rid}")
    RunStatus.model_validate(body)
    assert body["state"] == "done" and body["progress"] == 1.0
    status, summary = call("GET", f"/api/v1/runs/{rid}/summary")
    assert status == 200
    RunSummary.model_validate(summary)
    assert summary["totals"]["sent"] == 30 * 4
    assert summary["totals"]["received"] + summary["totals"]["lost_sensitivity"] \
        + summary["totals"]["lost_collision"] <= summary["totals"]["sent"] + 0


def test_summary_does_not_leak_keys_or_paths(finished_run):
    call, rid = finished_run["call"], finished_run["run_id"]
    blob = json.dumps([call("GET", f"/api/v1/runs/{rid}/summary")[1],
                       call("GET", f"/api/v1/runs/{rid}/devices")[1],
                       call("GET", f"/api/v1/runs/{rid}/events")[1]]).lower()
    for word in ("nwkskey", "appskey", "joinkey", "s_nwk", "lsim_data_key", "/home/", "terrain"):
        assert word not in blob


def test_devices_are_paginated_and_complete(finished_run):
    call, rid = finished_run["call"], finished_run["run_id"]
    status, page = call("GET", f"/api/v1/runs/{rid}/devices?limit=7")
    assert status == 200
    DevicePage.model_validate(page)
    seen = list(page["items"])
    cursor = page["next_cursor"]
    while cursor is not None:
        _, page = call("GET", f"/api/v1/runs/{rid}/devices?limit=7&cursor={cursor}")
        seen += page["items"]
        cursor = page["next_cursor"]
    assert [d["device_index"] for d in seen] == list(range(30))
    _, summary = call("GET", f"/api/v1/runs/{rid}/summary")
    assert sum(d["sent"] for d in seen) == summary["totals"]["sent"]


def test_events_are_ordered_paginated_and_hops_are_bounded(finished_run):
    call, rid = finished_run["call"], finished_run["run_id"]
    seqs, kinds, cursor = [], set(), 0
    while cursor is not None:
        _, page = call("GET", f"/api/v1/runs/{rid}/events?limit=50&cursor={cursor}")
        TracePage.model_validate(page)
        for ev in page["items"]:
            seqs.append(ev["seq"])
            kinds.add(ev["kind"])
            assert len(ev["hops"]) <= srv.MAX_TRACE_EVENTS_PER_RUN and len(ev["hops"]) <= 8
        cursor = page["next_cursor"]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    assert "uplink" in kinds and "join_request" in kinds


def test_other_owner_sees_nothing(finished_run):
    call, rid = finished_run["call"], finished_run["run_id"]
    other = finished_run["store"].issue("eve")
    for path in ("", "/summary", "/devices", "/events"):
        assert call("GET", f"/api/v1/runs/{rid}{path}", token=other)[0] == 404


def test_summary_is_refused_for_an_unknown_run(finished_run):
    call = finished_run["call"]
    assert call("GET", "/api/v1/runs/AAAAAAAAAAAAAAAAAAAAAA/summary")[0] == 404


def test_delete_terminal_run_removes_it(finished_run):
    call, rid = finished_run["call"], finished_run["run_id"]
    status, _ = call("DELETE", f"/api/v1/runs/{rid}")
    assert status == 204
    assert call("GET", f"/api/v1/runs/{rid}")[0] == 404


def test_run_is_reproducible_for_the_same_scenario(finished_run):
    call = finished_run["call"]
    body = {"scenario": _scenario(count=30, messages=4)}
    rids = []
    for _ in range(2):
        status, created = call("POST", "/api/v1/runs", body)
        assert status == 202
        rids.append(created["run_id"])
    results = []
    for rid in rids:
        deadline = time.time() + 180
        while time.time() < deadline:
            _, st = call("GET", f"/api/v1/runs/{rid}")
            if st["state"] == "done":
                break
            time.sleep(0.05)
        results.append(call("GET", f"/api/v1/runs/{rid}/summary")[1])
    assert results[0]["totals"] == results[1]["totals"]
    assert results[0]["scenario_sha256"] == results[1]["scenario_sha256"]


@pytest.fixture()
def gate(monkeypatch):
    """Bloque le premier calcul jusqu'à `gate.set()` : tests de file et de conflit déterministes."""
    release = threading.Event()
    original = srv.build_trace

    def blocked(*args, **kwargs):
        release.wait(60)
        return original(*args, **kwargs)

    monkeypatch.setattr(srv, "build_trace", blocked)
    yield release
    release.set()


def test_summary_before_end_is_conflict(api, gate):
    status, body = api.call("POST", "/api/v1/runs", {"scenario": _scenario()})
    assert status == 202
    rid = body["run_id"]
    status, err = api.call("GET", f"/api/v1/runs/{rid}/summary")
    assert status == 409 and err["code"] == "conflict"
    gate.set()
    assert _wait_done(api, rid)["state"] == "done"


def test_queued_run_can_be_cancelled(api, gate):
    _, first = api.call("POST", "/api/v1/runs", {"scenario": _scenario()})
    _, second = api.call("POST", "/api/v1/runs", {"scenario": _scenario(count=20)})
    rid2 = second["run_id"]
    assert api.call("GET", f"/api/v1/runs/{first['run_id']}")[1]["state"] in ("queued", "running")
    status, _ = api.call("DELETE", f"/api/v1/runs/{rid2}")
    assert status == 204
    gate.set()
    assert _wait_done(api, first["run_id"])["state"] == "done"
    assert _wait_done(api, rid2)["state"] == "cancelled"


def test_queue_is_bounded(tmp_path, gate):
    """File de taille 1 : le premier run est pris par le fil de calcul (bloqué), le second
    occupe la file, le troisième est refusé avec `limit_exceeded`."""
    tokens = tmp_path / "t.json"
    token = srv.TokenStore(tokens).issue("alice")
    server = srv.make_server("127.0.0.1", 0, tokens, max_queue=1)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        first = _raw_call(port, token, "POST", "/api/v1/runs", {"scenario": _scenario()})[1]
        deadline = time.time() + 10
        while _raw_call(port, token, "GET", f"/api/v1/runs/{first['run_id']}")[1]["state"] != "running":
            assert time.time() < deadline
            time.sleep(0.01)
        assert _raw_call(port, token, "POST", "/api/v1/runs", {"scenario": _scenario()})[0] == 202
        status, body = _raw_call(port, token, "POST", "/api/v1/runs", {"scenario": _scenario()})
        assert status == 422 and body["code"] == "limit_exceeded"
    finally:
        gate.set()
        server.shutdown()
        server.server_close()
        server.service.close()


def _raw_call(port, token, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    h = {"Authorization": "Bearer " + token}
    if body is not None:
        h["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, (json.loads(data) if data else None)


def test_failed_run_reports_a_problem_without_trace(api, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret /home/user/clé.bin")

    monkeypatch.setattr(srv, "build_trace", boom)
    status, body = api.call("POST", "/api/v1/runs", {"scenario": _scenario()})
    done = _wait_done(api, body["run_id"])
    assert done["state"] == "failed"
    assert done["problem"]["code"] == "run_failed"
    assert "secret" not in json.dumps(done) and "/home" not in json.dumps(done)


def _wait_finished(api, rid, token=None):
    return _wait_done(api, rid, token=token)


def test_multi_gateway_run_reports_per_gateway_and_totals_match(api):
    d = _scenario(count=200, messages=5)
    d.pop("gateway")
    d["gateways"] = [{"name": "a", "x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
                     {"name": "b", "x_m": 2500, "y_m": 0, "antenna_gain_dbi": 2.15}]
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d, "protocol": {
        "confirmed_uplinks": True, "downlink_every": 1}})
    assert status == 202
    rid = created["run_id"]
    assert _wait_done(api, rid)["state"] == "done"
    _, summary = api.call("GET", f"/api/v1/runs/{rid}/summary")
    RunSummary.model_validate(summary)
    assert "gateway" not in summary and [g["name"] for g in summary["gateways"]] == ["a", "b"]
    _, devices = api.call("GET", f"/api/v1/runs/{rid}/devices?limit=500")
    sent = sum(x["sent"] for x in devices["items"])
    recv = sum(x["received"] for x in devices["items"])
    assert sent == summary["totals"]["sent"] and recv == summary["totals"]["received"]
    _, page = api.call("GET", f"/api/v1/runs/{rid}/events?limit=500")
    total_up = 0
    cursor = 0
    while cursor is not None:
        _, page = api.call("GET", f"/api/v1/runs/{rid}/events?limit=500&cursor={cursor}")
        total_up += sum(1 for e in page["items"] if e["kind"] == "uplink"
                        and e["outcome"] == "received")
        cursor = page["next_cursor"]
    assert total_up == summary["totals"]["received"]


def test_protocol_run_totals_agree_with_events(api):
    """Régression : avec downlinks, les totaux de `run_scenario` divergeaient de la trace."""
    d = _scenario(count=300, messages=10)
    d["groups"][0]["placement"]["radius_m"] = 3000
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d, "protocol": {
        "confirmed_uplinks": True, "downlink_every": 1}})
    rid = created["run_id"]
    assert _wait_done(api, rid)["state"] == "done"
    _, summary = api.call("GET", f"/api/v1/runs/{rid}/summary")
    total_up = 0
    cursor = 0
    while cursor is not None:
        _, page = api.call("GET", f"/api/v1/runs/{rid}/events?limit=500&cursor={cursor}")
        total_up += sum(1 for e in page["items"] if e["kind"] == "uplink"
                        and e["outcome"] == "received")
        cursor = page["next_cursor"]
    assert total_up == summary["totals"]["received"]
    assert summary["totals"]["lost_gateway_busy"] >= 0


def test_obstacles_are_accepted_and_terrain_path_is_refused(api):
    env = {"obstacles": [{"x_min_m": 100, "y_min_m": -50, "x_max_m": 120, "y_max_m": 50,
                          "height_m": 20, "attenuation_db": 15}]}
    status, created = api.call("POST", "/api/v1/runs", {"scenario": _scenario(environment=env)})
    assert status == 202
    assert _wait_done(api, created["run_id"])["state"] == "done"
    status, body = api.call("POST", "/api/v1/runs", {"scenario": _scenario(
        environment={"terrain": {"type": "dem_csv", "path": "relief.csv"}})})
    assert status == 422 and body["code"] == "terrain_not_allowed"


def _energy_rows(api, rid):
    _, page = api.call("GET", f"/api/v1/runs/{rid}/devices?limit=500")
    return [(x["energy_per_message_j"], x["average_current_ua"]) for x in page["items"]]


def test_energy_without_protocol_matches_the_energy_model(api):
    """Sans protocole, l'énergie de l'API égale celle de `run_scenario` (aucune régression)."""
    d = _scenario()
    scenario = srv._build_scenario(ApiScenario.model_validate(d))
    expected = [(r.energy_per_message_j, r.average_current_ua)
                for r in run_scenario(scenario, energy_profile="rak4631").rows]
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d, "energy_profile": "rak4631"})
    assert status == 202
    assert _wait_done(api, created["run_id"])["state"] == "done"
    got = _energy_rows(api, created["run_id"])
    assert len(got) == len(expected)
    for (e1, c1), (e2, c2) in zip(got, expected):
        assert e1 == pytest.approx(e2, rel=1e-12) and c1 == pytest.approx(c2, rel=1e-12)


def test_energy_with_downlinks_counts_received_downlink_airtime(api):
    """Les descendantes reçues ajoutent de la réception : énergie ≥ sans protocole, et > pour certains."""
    d = _scenario(count=40, messages=4)
    _, plain = api.call("POST", "/api/v1/runs", {"scenario": d, "energy_profile": "rak4631"})
    _, withdl = api.call("POST", "/api/v1/runs", {
        "scenario": d, "energy_profile": "rak4631", "protocol": {"downlink_every": 1}})
    assert _wait_done(api, plain["run_id"])["state"] == "done"
    assert _wait_done(api, withdl["run_id"])["state"] == "done"
    base = _energy_rows(api, plain["run_id"])
    with_dl = _energy_rows(api, withdl["run_id"])
    pairs = [(a[0], b[0]) for a, b in zip(base, with_dl) if a[0] is not None]
    assert pairs and all(b >= a - 1e-15 for a, b in pairs)
    assert any(b > a for a, b in pairs)


def test_energy_is_accepted_in_multi_gateway(api):
    d = _scenario(count=60, messages=3)
    d.pop("gateway")
    d["gateways"] = [{"name": "a", "x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
                     {"name": "b", "x_m": 2500, "y_m": 0, "antenna_gain_dbi": 2.15}]
    status, created = api.call("POST", "/api/v1/runs", {
        "scenario": d, "energy_profile": "rak4631", "protocol": {"downlink_every": 1}})
    assert status == 202
    rid = created["run_id"]
    assert _wait_done(api, rid)["state"] == "done"
    _, summary = api.call("GET", f"/api/v1/runs/{rid}/summary")
    assert summary["energy_profile"] == "rak4631" and "gateways" in summary
    assert any(e is not None for e, _ in _energy_rows(api, rid))


def test_terrain_catalog_lists_only_valid_ids(api_relief):
    status, body = api_relief.call("GET", "/api/v1/terrains")
    assert status == 200
    listing = TerrainList.model_validate(body)
    assert [t.id for t in listing.items] == ["quartier"]
    expected = load_dem_csv(EXAMPLES / "relief_quartier_dem.csv").sha256
    assert listing.items[0].sha256 == expected


def test_terrain_id_is_resolved_on_the_server_and_hashed_into_the_scenario(api_relief):
    env = {"gateway_height_m": 25, "device_height_m": 1.5, "obstacles": [
        {"x_min_m": 400, "y_min_m": -150, "x_max_m": 550, "y_max_m": 150,
         "height_m": 24, "attenuation_db": 18}]}
    d = _scenario(count=50, messages=2, environment=env)
    _, plain = api_relief.call("POST", "/api/v1/scenarios/validate", {"scenario": d})
    status, with_relief = api_relief.call("POST", "/api/v1/scenarios/validate",
                                          {"scenario": d, "terrain_id": "quartier"})
    assert status == 200 and with_relief["valid"] is True
    assert with_relief["scenario_sha256"] != plain["scenario_sha256"]
    status, created = api_relief.call("POST", "/api/v1/runs", {
        "scenario": d, "terrain_id": "quartier"})
    assert status == 202
    rid = created["run_id"]
    assert _wait_done(api_relief, rid)["state"] == "done"
    _, summary = api_relief.call("GET", f"/api/v1/runs/{rid}/summary")
    assert summary["scenario_sha256"] == with_relief["scenario_sha256"]


def test_unknown_or_unsafe_terrain_ids_are_refused(api_relief):
    d = _scenario()
    status, body = api_relief.call("POST", "/api/v1/runs", {"scenario": d, "terrain_id": "absent"})
    assert status == 422 and body["field"] == "terrain_id"
    for bad in ("../quartier", "Quartier", "a/b", ""):
        status, body = api_relief.call("POST", "/api/v1/runs", {"scenario": d, "terrain_id": bad})
        assert status == 422, bad


def test_without_catalog_every_terrain_id_is_unknown(api):
    status, body = api.call("POST", "/api/v1/runs", {"scenario": _scenario(), "terrain_id": "quartier"})
    assert status == 422 and body["field"] == "terrain_id"
    status, body = api.call("GET", "/api/v1/terrains")
    assert status == 200 and body == {"items": []}


def test_join_is_accepted_in_multi_gateway_and_appears_in_the_trace(api):
    d = _scenario(count=60, messages=4)
    d.pop("gateway")
    d["gateways"] = [{"name": "a", "x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
                     {"name": "b", "x_m": 2500, "y_m": 0, "antenna_gain_dbi": 2.15}]
    status, created = api.call("POST", "/api/v1/runs", {
        "scenario": d, "protocol": {"join": True, "confirmed_uplinks": True, "downlink_every": 1}})
    assert status == 202
    rid = created["run_id"]
    assert _wait_done(api, rid)["state"] == "done"
    _, summary = api.call("GET", f"/api/v1/runs/{rid}/summary")
    RunSummary.model_validate(summary)
    kinds = set()
    cursor = 0
    while cursor is not None:
        _, page = api.call("GET", f"/api/v1/runs/{rid}/events?limit=500&cursor={cursor}")
        kinds |= {e["kind"] for e in page["items"]}
        cursor = page["next_cursor"]
    assert {"join_request", "join_accept"} <= kinds


def test_runs_survive_a_restart_and_interrupted_ones_fail(tmp_path):
    tokens = tmp_path / "t.json"
    token = srv.TokenStore(tokens).issue("alice")
    db = str(tmp_path / "runs.sqlite3")
    server = srv.make_server("127.0.0.1", 0, tokens, runs_db=db)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    _, created = _raw_call(port, token, "POST", "/api/v1/runs", {"scenario": _scenario()})
    rid = created["run_id"]
    deadline = time.time() + 120
    while _raw_call(port, token, "GET", f"/api/v1/runs/{rid}")[1]["state"] != "done":
        assert time.time() < deadline
        time.sleep(0.05)
    server.shutdown()
    server.server_close()
    server.service.close()
    server.service._store.close()

    server2 = srv.make_server("127.0.0.1", 0, tokens, runs_db=db)
    threading.Thread(target=server2.serve_forever, daemon=True).start()
    try:
        port2 = server2.server_address[1]
        status, summary = _raw_call(port2, token, "GET", f"/api/v1/runs/{rid}/summary")
        assert status == 200 and summary["totals"]["sent"] > 0
    finally:
        server2.shutdown()
        server2.server_close()
        server2.service.close()
        server2.service._store.close()

    # Un run encore en file au moment de l'arrêt est marqué interrompu au redémarrage.
    store = srv.RunStore(db)
    store.insert_run("interruptedrun1", "alice", 1, "0" * 64, 0)
    store.close()
    server3 = srv.make_server("127.0.0.1", 0, tokens, runs_db=db)
    threading.Thread(target=server3.serve_forever, daemon=True).start()
    try:
        status, st = _raw_call(server3.server_address[1], token, "GET",
                               "/api/v1/runs/interruptedrun1")
        assert status == 200 and st["state"] == "failed"
        assert st["problem"]["code"] == "run_failed"
    finally:
        server3.shutdown()
        server3.server_close()
        server3.service.close()
        server3.service._store.close()


def test_rate_limit_answers_429_with_retry_after(tmp_path):
    tokens = tmp_path / "t.json"
    token = srv.TokenStore(tokens).issue("alice")
    server = srv.make_server("127.0.0.1", 0, tokens)
    server.service.limiter = srv.RateLimiter(per_minute=60, burst=2)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        codes = [_raw_call(port, token, "GET", "/api/v1/regions")[0] for _ in range(3)]
        assert codes == [200, 200, 429]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/v1/regions", headers={"Authorization": "Bearer " + token})
        resp = conn.getresponse()
        body = json.loads(resp.read())
        assert resp.status == 429 and body["code"] == "rate_limited"
        assert int(resp.getheader("Retry-After")) >= 1
    finally:
        server.shutdown()
        server.server_close()
        server.service.close()


def test_rate_limiter_refills_over_time():
    now = [0.0]
    lim = srv.RateLimiter(per_minute=60, burst=1, clock=lambda: now[0])
    assert lim.take("a") is None
    assert lim.take("a") is not None
    now[0] += 1.0
    assert lim.take("a") is None
    assert lim.take("b") is None  # compteurs par propriétaire


def _self_signed(tmp):
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")]),
                critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp / "cert.pem", tmp / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


def test_tls_serves_https_and_refuses_plain_http_clients(tmp_path):
    import ssl
    cert, key = _self_signed(tmp_path)
    tokens = tmp_path / "t.json"
    token = srv.TokenStore(tokens).issue("alice")
    server = srv.make_server("127.0.0.1", 0, tokens, tls=srv.make_tls_context(cert, key))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        ctx = ssl.create_default_context(cafile=str(cert))
        conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=10)
        conn.request("GET", "/api/v1/regions", headers={"Authorization": "Bearer " + token})
        resp = conn.getresponse()
        assert resp.status == 200
        resp.read()
        conn.close()
        # Un client en clair ne doit obtenir aucune réponse de l'API.
        plain = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        with pytest.raises(Exception):
            plain.request("GET", "/api/v1/health")
            plain.getresponse().read()
    finally:
        server.shutdown()
        server.server_close()
        server.service.close()


def test_serve_refuses_plain_http_outside_loopback(tmp_path):
    tokens = tmp_path / "t.json"
    with pytest.raises(SystemExit):
        srv.main(["serve", "--tokens", str(tokens), "--runs-db", ":memory:",
                  "--host", "0.0.0.0", "--port", "0"])

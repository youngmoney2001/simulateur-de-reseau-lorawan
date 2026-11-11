"""Le run publié par l'API porte la latence des descentes réseau (`lsim.api_server`).

Deux choses sont vérifiées ici, et c'est la seconde qui compte le plus :

1. un run qui déclare des descentes publie leur latence, et la classe la change ;
2. un run qui n'en déclare aucune ne publie **rien** — pas un objet de zéros. Des zéros
   diraient « aucune descente livrée », ce qui serait faux d'un run qui n'en a pas demandé.
   C'est aussi ce qui garantit qu'un run écrit avant ne voit pas son résumé changer.
"""

import http.client
import json
import threading
import time
from pathlib import Path

import pytest

from lsim import api_server as srv
from lsim.api_contract import RunSummary


def _scenario(**groupe) -> dict:
    base = {
        "schema_version": 1,
        "name": "descentes api",
        "seed": 7,
        "gateway": {"x_m": 0, "y_m": 0},
        "groups": [{
            "name": "g", "count": 1,
            "placement": {"type": "explicit", "positions": [[100, 0]]},
            "spreading_factor": 7, "period_s": 60, "messages": 3,
        }],
    }
    base["groups"][0].update(groupe)
    return base


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("descentes")
    tokens = tmp / "tokens.json"
    store = srv.TokenStore(tokens)
    token = store.issue("alice")
    server = srv.make_server("127.0.0.1", 0, tokens)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def call(method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=120)
        headers = {"Authorization": "Bearer " + token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, (json.loads(data) if data else None)

    def run(**groupe):
        status, body = call("POST", "/api/v1/runs", {"scenario": _scenario(**groupe)})
        assert status == 202, body
        run_id = body["run_id"]
        deadline = time.time() + 180
        while time.time() < deadline:
            _, st = call("GET", f"/api/v1/runs/{run_id}")
            if st["state"] in ("done", "failed"):
                break
            time.sleep(0.05)
        assert st["state"] == "done", st
        _, summary = call("GET", f"/api/v1/runs/{run_id}/summary")
        return RunSummary.model_validate(summary)

    yield run
    server.shutdown()
    server.server_close()
    server.service.close()


def test_a_run_without_requests_publishes_nothing(api):
    """Ni la clé, ni un objet de zéros : un run écrit avant garde son résumé."""
    assert api().downlink is None


def test_the_latency_published_is_the_one_the_class_decides(api):
    """Mesuré par le moteur : 0 s en classe C, 51 s en classe A (mêmes chiffres qu'au CLI)."""
    c = api(device_class="C", downlink={"count": 1, "first_request_s": 10}).downlink
    a = api(device_class="A", downlink={"count": 1, "first_request_s": 10}).downlink
    assert c is not None and a is not None
    assert (c.requested, c.delivered) == (1, 1)
    assert (a.requested, a.delivered) == (1, 1)
    assert c.latency_mean_s == pytest.approx(0.0, abs=1e-6)
    assert 50.0 < a.latency_mean_s < 52.0
    assert a.latency_mean_s > c.latency_mean_s


def test_class_b_is_not_published_as_faster_than_a(api):
    """Selon la périodicité, la classe B encadre la classe A — le résumé le laisse voir."""
    a = api(device_class="A", downlink={"count": 1, "first_request_s": 10}).downlink
    rapide = api(device_class="B",
                 downlink={"count": 1, "first_request_s": 10, "periodicity": 0}).downlink
    lent = api(device_class="B",
               downlink={"count": 1, "first_request_s": 10, "periodicity": 7}).downlink
    assert rapide.latency_mean_s < a.latency_mean_s < lent.latency_mean_s

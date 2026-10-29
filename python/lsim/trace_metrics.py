"""Indicateurs tirés de la trace d'un run multi-passerelles (publiés dans le résumé).

- Latence d'un uplink de donnée : instant de remise au LNS moins instant d'émission, attribué à la
  passerelle qui l'a remise (saut `ns` de l'événement). Les joins sont exclus.
- Liens mesh observés : sauts mesh livrés (`mesh_hop`, issue `delivered`), comptés par émetteur et
  récepteur. Un lien compté prouve qu'une trame a effectivement franchi ce saut.

Fonction pure : aucune dépendance au moteur natif, testable sur une trace construite à la main.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

NS_NAME = "ns"
GW_PREFIX = "gw:"
MAX_INBOUND_LINKS = 64


@dataclass
class GatewayMetrics:
    latency_samples_ms: list = field(default_factory=list)
    inbound: Counter = field(default_factory=Counter)   # émetteur -> sauts mesh livrés

    def percentile_ms(self, q: float) -> Optional[float]:
        if not self.latency_samples_ms:
            return None
        ordered = sorted(self.latency_samples_ms)
        rank = max(1, math.ceil(q * len(ordered)))      # méthode du rang le plus proche
        return round(ordered[rank - 1], 3)


def _name(gw_id: str) -> Optional[str]:
    return gw_id[len(GW_PREFIX):] if gw_id.startswith(GW_PREFIX) else None


def gateway_metrics(events: Iterable, names: Sequence[str]) -> dict[str, GatewayMetrics]:
    """Métriques par passerelle (toutes les passerelles de `names` sont présentes)."""
    out = {name: GatewayMetrics() for name in names}
    for ev in events:
        if ev.kind == "uplink":
            ns_hops = [h for h in ev.hops if h.to_id == NS_NAME and h.outcome == "delivered"]
            if ns_hops:
                h = ns_hops[-1]
                gw = _name(h.from_id)
                if gw in out:
                    out[gw].latency_samples_ms.append((h.t_ns - ev.t_ns) / 1e6)
        elif ev.kind == "mesh_hop":
            for h in ev.hops:
                sender, receiver = _name(h.from_id), _name(h.to_id)
                if h.outcome == "delivered" and sender in out and receiver in out:
                    out[receiver].inbound[sender] += 1
    return out


def report_fields(metrics: Optional[GatewayMetrics]) -> dict:
    """Champs d'un `GatewayReportOut` (optionnels : absents sans mesure)."""
    if metrics is None:
        return {}
    fields: dict = {"latency_samples": len(metrics.latency_samples_ms),
                    "latency_p50_ms": metrics.percentile_ms(0.5),
                    "latency_p95_ms": metrics.percentile_ms(0.95)}
    if metrics.inbound:
        fields["mesh_inbound"] = [{"from_gateway": s, "delivered": n}
                                  for s, n in sorted(metrics.inbound.items())][:MAX_INBOUND_LINKS]
    return fields

"""Passerelles multiples avec downlinks : passerelle répondante, demi-duplex par passerelle.

Le calcul est fait par le cœur natif (`simulate_uplinks_multi_downlinks`), dans l'ordre de FIN des
émissions : aucune itération n'est nécessaire, et il n'y a donc pas d'oscillation entre uplinks
bloqués et downlinks absents.

Modèle (voir `lsim/engine.hpp`) :
- chaque uplink décodé par au moins une passerelle est acquitté ou reçoit une charge par la
  meilleure passerelle décodeuse (plus fort RSSI), en fenêtre RX1 (+1 s) ;
- chaque passerelle sérialise ses downlinks ; hors fenêtre RX1 du dispositif, le downlink est perdu ;
- une passerelle ne décode pas les trames pendant ses propres downlinks ;
- le dispositif ne reçoit pas s'il émet pendant sa fenêtre RX1 ;
- réception du downlink par réciprocité sur le RSSI de la passerelle répondante.

Hors périmètre : join-accept (protocole mono-passerelle dans `lsim.trace_events`), relais mesh.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from lsim.environment import Environment
from lsim.simulator import (
    DownlinkRule,
    EndDevice,
    Gateway,
    MultiDownlinkResult,
    Propagation,
    simulate_multi_downlinks,
)
from lsim.trace_events import ProtocolOptions

# Issues des downlinks, telles que renvoyées par le cœur.
DOWNLINK_OUTCOMES = {
    0: "delivered",
    1: "lost_sensitivity",
    2: "gateway_busy",
    3: "device_transmitting",
}


@dataclass(frozen=True)
class DownlinkEvent:
    device_index: int
    gateway_index: int
    kind: str          # "ack" ou "downlink"
    t_open_ns: int     # ouverture de RX1 chez le dispositif
    start_ns: Optional[int]
    outcome: str


@dataclass(frozen=True)
class MultiRun:
    result: MultiDownlinkResult
    downlinks: tuple[DownlinkEvent, ...]
    gateway_tx: tuple[tuple[tuple[int, int], ...], ...]  # par passerelle, [début, fin) en ns


def rule_from_options(options: ProtocolOptions) -> DownlinkRule:
    """Traduit les options protocole (mono-passerelle) en règle multi-passerelles."""
    return DownlinkRule(
        ack_uplinks=options.confirmed_uplinks,
        every=options.downlink_every,
        payload_bytes=options.downlink_payload_bytes,
        gateway_tx_power_dbm=options.gateway_tx_power_dbm,
        device_antenna_gain_dbi=options.device_antenna_gain_dbi,
        device_rx_offset_db=options.device_rx_offset_db,
    )


def simulate_multi_with_downlinks(devices: Sequence[EndDevice], gateways: Sequence[Gateway],
                                  propagation: Propagation,
                                  environment: Optional[Environment] = None,
                                  options: ProtocolOptions = ProtocolOptions()) -> MultiRun:
    result = simulate_multi_downlinks(devices, gateways, propagation, rule_from_options(options),
                                      environment)
    events = []
    per_gw: list[list[tuple[int, int]]] = [[] for _ in gateways]
    for r in result.downlinks:
        start = r.start_ns if r.start_ns >= 0 else None
        events.append(DownlinkEvent(r.device_index, r.gateway_index,
                                    "downlink" if r.data else "ack",
                                    r.t_open_ns, start, DOWNLINK_OUTCOMES[r.outcome]))
        if start is not None:
            per_gw[r.gateway_index].append((start, r.end_ns))
    return MultiRun(result=result, downlinks=tuple(events),
                    gateway_tx=tuple(tuple(sorted(per)) for per in per_gw))

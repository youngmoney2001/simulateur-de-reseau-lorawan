"""Backhaul mesh par relais LoRa : passerelles relais vers une passerelle frontière.

Modèle (style ChirpStack Gateway Mesh) :
- les capteurs ne sont pas concernés : seules les passerelles relaient ;
- chaque passerelle qui a reçu une trame la transmet saut par saut sur la bande
  mesh, jusqu'à la passerelle frontière, qui la remet au serveur (LNS) ;
- au plus `MAX_HOPS` sauts (8 par défaut, valeur ChirpStack) ;
- demi-duplex : une passerelle ne reçoit pas pendant ses propres émissions ;
- collision : deux réceptions simultanées au même récepteur ; la plus forte
  survit si elle dépasse l'autre de `capture_db`, sinon les deux sont perdues.

Sensibilité : tableau SX1280 « low power mode », CR 4/5, PER 1 %, 10 octets
(Semtech DS.SX1280-1 Rev 3.0, table 6-1). Le mode haute sensibilité donne 2 dB
de mieux, mais seulement aux points publiés (SF12/203 kHz) : on reste donc
sur le tableau complet, plus conservateur.

Temps d'antenne : formule AN1200.13 en fraction exacte (le cœur natif ne
gère que 125/250/500 kHz ; le test de cohérence vérifie l'accord à 125 kHz).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional, Sequence

from lsim.radio import LogDistanceModel

MAX_HOPS = 8
MESH_BAND_HZ = 2_400_000_000

# Tableau SX1280 : BW (kHz) -> sensibilités SF5..SF12 (dBm).
_SX1280_SENSITIVITY_DBM: dict[int, tuple[int, ...]] = {
    203: (-109, -111, -115, -118, -121, -124, -127, -130),
    406: (-107, -110, -113, -116, -119, -122, -125, -128),
    812: (-105, -108, -112, -115, -117, -120, -123, -126),
    1625: (-99, -103, -106, -109, -111, -114, -117, -120),
}


def sx1280_sensitivity_dbm(spreading_factor: int, bandwidth_khz: int) -> int:
    """Sensibilité SX1280 (dBm), mode basse consommation, CR 4/5, PER 1 %."""
    if bandwidth_khz not in _SX1280_SENSITIVITY_DBM:
        raise ValueError("bandwidth_khz doit valoir 203, 406, 812 ou 1625")
    if not 5 <= spreading_factor <= 12:
        raise ValueError("spreading_factor doit être compris entre 5 et 12")
    return _SX1280_SENSITIVITY_DBM[bandwidth_khz][spreading_factor - 5]


def time_on_air_ns(spreading_factor: int, bandwidth_hz: int, payload_bytes: int,
                   coding_rate: int = 1, preamble_symbols: int = 8) -> int:
    """Temps d'antenne (ns), AN1200.13, CRC activé, en-tête explicite.

    `coding_rate` : 1 = 4/5 … 4 = 4/8, comme dans `RadioConfig`.
    """
    if not 5 <= spreading_factor <= 12:
        raise ValueError("spreading_factor doit être compris entre 5 et 12")
    if bandwidth_hz <= 0:
        raise ValueError("bandwidth_hz doit être > 0")
    if not 0 <= payload_bytes <= 255:
        raise ValueError("payload_bytes doit être compris entre 0 et 255")
    if not 1 <= coding_rate <= 4:
        raise ValueError("coding_rate doit être compris entre 1 et 4")
    t_sym_ns = Fraction(2 ** spreading_factor * 1_000_000_000, bandwidth_hz)
    de = 1 if t_sym_ns > 16_000_000 else 0
    num = 8 * payload_bytes - 4 * spreading_factor + 28 + 16
    den = 4 * (spreading_factor - 2 * de)
    n_payload = 8 + max(-(-num // den) * (coding_rate + 4), 0)
    total = (Fraction(preamble_symbols) + Fraction(17, 4) + n_payload) * t_sym_ns
    return round(total)


@dataclass(frozen=True)
class MeshNode:
    gateway_id: str
    x_m: float
    y_m: float
    mesh_capable: bool = True
    tx_power_dbm: float = 27.0
    antenna_gain_dbi: float = 0.0


@dataclass(frozen=True)
class MeshRadio:
    """Paramètres de la liaison mesh sur 2,4 GHz (toutes les passerelles identiques)."""

    spreading_factor: int = 12
    bandwidth_khz: int = 203
    coding_rate: int = 1
    payload_bytes: int = 32  # taille d'une trame relayée (LoRaWAN + enveloppe mesh)
    capture_db: float = 6.0

    def __post_init__(self) -> None:
        sx1280_sensitivity_dbm(self.spreading_factor, self.bandwidth_khz)  # validation
        if not 0 <= self.payload_bytes <= 255:
            raise ValueError("payload_bytes doit être compris entre 0 et 255")
        if self.capture_db < 0:
            raise ValueError("capture_db ne peut pas être négatif")

    @property
    def sensitivity_dbm(self) -> int:
        return sx1280_sensitivity_dbm(self.spreading_factor, self.bandwidth_khz)

    @property
    def airtime_ns(self) -> int:
        return time_on_air_ns(self.spreading_factor, self.bandwidth_khz * 1000,
                              self.payload_bytes, self.coding_rate)


@dataclass(frozen=True)
class MeshGraph:
    """Routes vers la frontière et puissances reçues sur chaque lien (réciproques)."""

    border_id: str
    routes: dict[str, tuple[str, ...]]          # gw -> (saut1, ..., frontière) ; () pour la frontière
    rssi_dbm: dict[tuple[str, str], float]      # (émetteur, récepteur) -> dBm, liens faisables

    def route(self, gateway_id: str) -> Optional[tuple[str, ...]]:
        return self.routes.get(gateway_id)


def build_mesh(nodes: Sequence[MeshNode], border_id: str, radio: MeshRadio,
               path_loss: Optional[LogDistanceModel] = None,
               max_hops: int = MAX_HOPS) -> MeshGraph:
    """Calcule les liens faisables et la route la plus courte vers la frontière.

    Un lien A-B existe si la puissance reçue atteint la sensibilité mesh dans
    les deux sens. Toutes les passerelles d'une route, frontière comprise,
    doivent avoir une radio mesh.
    """
    if not 1 <= max_hops <= MAX_HOPS:
        raise ValueError(f"max_hops doit être compris entre 1 et {MAX_HOPS}")
    ids = [n.gateway_id for n in nodes]
    if len(set(ids)) != len(ids):
        raise ValueError("identifiants de passerelles en double")
    by_id = {n.gateway_id: n for n in nodes}
    if border_id not in by_id:
        raise ValueError("passerelle frontière inconnue")
    if not by_id[border_id].mesh_capable:
        raise ValueError("la passerelle frontière doit avoir une radio mesh")
    model = path_loss or LogDistanceModel(frequency_hz=MESH_BAND_HZ)

    mesh_nodes = [n for n in nodes if n.mesh_capable]
    rssi: dict[tuple[str, str], float] = {}
    adj: dict[str, list[str]] = {n.gateway_id: [] for n in mesh_nodes}
    for i, a in enumerate(mesh_nodes):
        for b in mesh_nodes[i + 1:]:
            d = max(((a.x_m - b.x_m) ** 2 + (a.y_m - b.y_m) ** 2) ** 0.5, 1.0)
            pl = model.path_loss_db(d)
            ab = a.tx_power_dbm + a.antenna_gain_dbi - pl + b.antenna_gain_dbi
            ba = b.tx_power_dbm + b.antenna_gain_dbi - pl + a.antenna_gain_dbi
            if ab >= radio.sensitivity_dbm and ba >= radio.sensitivity_dbm:
                rssi[(a.gateway_id, b.gateway_id)] = ab
                rssi[(b.gateway_id, a.gateway_id)] = ba
                adj[a.gateway_id].append(b.gateway_id)
                adj[b.gateway_id].append(a.gateway_id)

    # BFS depuis la frontière : routes les plus courtes, bornées par max_hops.
    routes: dict[str, tuple[str, ...]] = {border_id: ()}
    frontier = [border_id]
    for _ in range(max_hops):
        nxt: list[str] = []
        for u in frontier:
            for v in adj.get(u, ()):
                if v not in routes:
                    routes[v] = (u,) + routes[u]
                    nxt.append(v)
        frontier = nxt
        if not frontier:
            break
    return MeshGraph(border_id=border_id, routes=routes, rssi_dbm=rssi)


@dataclass(frozen=True)
class MeshFrame:
    frame_id: int
    rx_gateway_id: str   # passerelle qui a reçu la trame sur la bande d'accès
    t_ns: int            # fin de réception sur l'accès


@dataclass(frozen=True)
class MeshDelivery:
    frame_id: int
    delivered: bool
    hops: int
    latency_ns: Optional[int]
    loss: str = ""       # "" si livré ; sinon : no_route, half_duplex, collision


@dataclass
class MeshResult:
    deliveries: list[MeshDelivery] = field(default_factory=list)

    @property
    def delivered(self) -> int:
        return sum(1 for d in self.deliveries if d.delivered)

    def count(self, loss: str) -> int:
        return sum(1 for d in self.deliveries if d.loss == loss)


@dataclass
class _Hop:
    frame: MeshFrame
    index: int                 # numéro du saut (0 = premier)
    sender: str
    path: tuple[str, ...]      # passerelles restantes, la dernière est la frontière
    start: int
    end: int
    rssi: float


def forward_frames(frames: Sequence[MeshFrame], graph: MeshGraph,
                   radio: MeshRadio) -> MeshResult:
    """Relais saut par saut sur la bande mesh, par événements datés.

    Un saut part dès que l'émetteur est libre (file FIFO). Sa réception est
    évaluée à sa fin : à cette date, tous les sauts qui commencent avant sont
    connus, donc demi-duplex et collisions sont exacts.
    """
    airtime = radio.airtime_ns
    cap = radio.capture_db
    busy_until: dict[str, int] = {}
    tx_intervals: dict[str, list[tuple[int, int]]] = {}
    rx_hops: dict[str, list[_Hop]] = {}
    results: dict[int, MeshDelivery] = {}
    heap: list[tuple[int, int, _Hop]] = []
    seq = 0

    def schedule(hop: _Hop) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(heap, (hop.end, seq, hop))

    def transmit(frame: MeshFrame, index: int, sender: str, path: tuple[str, ...],
                 ready: int) -> None:
        receiver = path[0]
        start = max(ready, busy_until.get(sender, 0))
        end = start + airtime
        busy_until[sender] = end
        tx_intervals.setdefault(sender, []).append((start, end))
        hop = _Hop(frame, index, sender, path, start, end, graph.rssi_dbm[(sender, receiver)])
        rx_hops.setdefault(receiver, []).append(hop)
        schedule(hop)

    for f in sorted(frames, key=lambda x: (x.t_ns, x.frame_id)):
        route = graph.route(f.rx_gateway_id)
        if route is None:
            results[f.frame_id] = MeshDelivery(f.frame_id, False, 0, None, "no_route")
        elif not route:
            results[f.frame_id] = MeshDelivery(f.frame_id, True, 0, 0)
        else:
            transmit(f, 0, f.rx_gateway_id, route, f.t_ns)

    frames_by_id = {f.frame_id: f for f in frames}
    while heap:
        _, _, hop = heapq.heappop(heap)
        receiver = hop.path[0]
        # Demi-duplex : le récepteur émettait pendant tout ou partie de la trame.
        if any(s < hop.end and hop.start < e for (s, e) in tx_intervals.get(receiver, ())):
            loss = "half_duplex"
        else:
            # Collision : un autre saut audible se chevauche et n'est pas
            # plus fort de `cap` dB.
            loss = ""
            for other in rx_hops.get(receiver, ()):
                if other is hop or not (other.start < hop.end and hop.start < other.end):
                    continue
                if hop.rssi < other.rssi + cap:
                    loss = "collision"
                    break
        fid = hop.frame.frame_id
        if loss:
            results[fid] = MeshDelivery(fid, False, hop.index + 1, None, loss)
        elif len(hop.path) == 1:
            results[fid] = MeshDelivery(fid, True, hop.index + 1,
                                        hop.end - hop.frame.t_ns)
        else:
            transmit(hop.frame, hop.index + 1, receiver, hop.path[1:], hop.end)
    ordered = [results[f.frame_id] for f in sorted(frames_by_id.values(),
                                                   key=lambda x: x.frame_id)]
    return MeshResult(deliveries=ordered)

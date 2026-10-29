"""Backhaul mesh par relais LoRa : passerelles relais vers une passerelle frontière.

Les calculs (sensibilité SX1280, airtime, routes, relais saut par saut, demi-duplex,
collisions) sont dans le cœur natif (`core/src/mesh.cpp`). Ce module valide les
entrées, calcule les puissances reçues avec le modèle de propagation, et convertit
les résultats.

Modèle (style ChirpStack Gateway Mesh) :
- seules les passerelles relaient ; les capteurs ne sont pas concernés ;
- une passerelle qui a reçu une trame la transmet saut par saut jusqu'à la
  frontière, qui la remet au serveur ;
- au plus `MAX_HOPS` sauts (8, valeur ChirpStack) ;
- demi-duplex : une passerelle ne reçoit pas pendant son propre relais ;
- collision : la plus forte survit si elle dépasse l'autre de `capture_db`.

Sensibilité : tableau SX1280 « low power mode », CR 4/5, PER 1 %, 10 octets
(Semtech DS.SX1280-1 Rev 3.0, table 6-1), plus conservateur que le mode haute
sensibilité, dont seul le point SF12/203 kHz est publié.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Optional, Sequence

from lsim._native import LIB as _LIB
from lsim._native import _CMeshDelivery, _CMeshFrame, _CMeshRadio
from lsim.lora import StatusError
from lsim.radio import LogDistanceModel

MAX_HOPS = 8
MAX_NODES = 64          # kMaxGateways côté natif
MESH_BAND_HZ = 2_400_000_000
_BW_KHZ = (203, 406, 812, 1625)
_LOSS_NAMES = ("", "no_route", "half_duplex", "collision")


def _check(status: int) -> None:
    if status != 0:
        raise StatusError(status)


def _c_radio(radio: "MeshRadio", bandwidth_hz: Optional[int] = None) -> _CMeshRadio:
    return _CMeshRadio(
        spreading_factor=radio.spreading_factor,
        coding_rate=radio.coding_rate,
        bandwidth_hz=radio.bandwidth_khz * 1000 if bandwidth_hz is None else bandwidth_hz,
        payload_bytes=radio.payload_bytes,
        preamble_symbols=8,
        capture_db=radio.capture_db,
    )


def sx1280_sensitivity_dbm(spreading_factor: int, bandwidth_khz: int) -> int:
    """Sensibilité SX1280 (dBm), mode basse consommation, CR 4/5, PER 1 %."""
    if bandwidth_khz not in _BW_KHZ:
        raise ValueError("bandwidth_khz doit valoir 203, 406, 812 ou 1625")
    if not 5 <= spreading_factor <= 12:
        raise ValueError("spreading_factor doit être compris entre 5 et 12")
    radio = MeshRadio(spreading_factor=spreading_factor, bandwidth_khz=bandwidth_khz)
    return radio.sensitivity_dbm


def time_on_air_ns(spreading_factor: int, bandwidth_hz: int, payload_bytes: int,
                   coding_rate: int = 1, preamble_symbols: int = 8) -> int:
    """Temps d'antenne (ns), AN1200.13, optimisation bas débit si Tsym > 16 ms.

    Accepte toute bande positive (125 kHz comme 2,4 GHz) ; à 125/250/500 kHz,
    le résultat est identique à `lsim.time_on_air_ns` (test de cohérence).
    """
    if not 5 <= spreading_factor <= 12:
        raise ValueError("spreading_factor doit être compris entre 5 et 12")
    if bandwidth_hz <= 0:
        raise ValueError("bandwidth_hz doit être > 0")
    if not 0 <= payload_bytes <= 255:
        raise ValueError("payload_bytes doit être compris entre 0 et 255")
    if not 1 <= coding_rate <= 4:
        raise ValueError("coding_rate doit être compris entre 1 et 4")
    if not 6 <= preamble_symbols <= 65_535:
        raise ValueError("preamble_symbols doit être compris entre 6 et 65535")
    c = _CMeshRadio(spreading_factor=spreading_factor, coding_rate=coding_rate,
                    bandwidth_hz=bandwidth_hz, payload_bytes=payload_bytes,
                    preamble_symbols=preamble_symbols, capture_db=0.0)
    out = ctypes.c_int64(0)
    _check(_LIB.lsim_mesh_airtime_ns(ctypes.byref(c), ctypes.byref(out)))
    return out.value


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
    """Paramètres de la liaison mesh sur 2,4 GHz (passerelles identiques)."""

    spreading_factor: int = 12
    bandwidth_khz: int = 203
    coding_rate: int = 1
    payload_bytes: int = 32   # trame relayée (LoRaWAN + enveloppe mesh)
    capture_db: float = 6.0

    def __post_init__(self) -> None:
        if self.bandwidth_khz not in _BW_KHZ:
            raise ValueError("bandwidth_khz doit valoir 203, 406, 812 ou 1625")
        if not 5 <= self.spreading_factor <= 12:
            raise ValueError("spreading_factor doit être compris entre 5 et 12")
        if not 1 <= self.coding_rate <= 4:
            raise ValueError("coding_rate doit être compris entre 1 et 4")
        if not 0 <= self.payload_bytes <= 255:
            raise ValueError("payload_bytes doit être compris entre 0 et 255")
        if not self.capture_db >= 0:
            raise ValueError("capture_db ne peut pas être négatif")

    @property
    def sensitivity_dbm(self) -> int:
        out = ctypes.c_int32(0)
        _check(_LIB.lsim_mesh_sensitivity_dbm(ctypes.byref(_c_radio(self)), ctypes.byref(out)))
        return out.value

    @property
    def airtime_ns(self) -> int:
        out = ctypes.c_int64(0)
        _check(_LIB.lsim_mesh_airtime_ns(ctypes.byref(_c_radio(self)), ctypes.byref(out)))
        return out.value


@dataclass
class MeshGraph:
    """Routes vers la frontière, calculées par le natif."""

    border_id: str
    ids: tuple[str, ...]
    next_hop: tuple[int, ...]          # indice du saut suivant, -1 si aucune route
    rssi: ctypes.Array                 # rssi[i*n+j] : reçu en j, émis par i (dBm)
    capable: tuple[int, ...]
    radio: MeshRadio
    _index: dict = field(default_factory=dict, repr=False)

    def route(self, gateway_id: str) -> Optional[tuple[str, ...]]:
        """Suite de passerelles jusqu'à la frontière (frontière incluse), () pour elle-même."""
        i = self._index.get(gateway_id)
        if i is None or self.next_hop[i] < 0:
            return None
        border = self._index[self.border_id]
        path: list[str] = []
        j = i
        while j != border:
            j = self.next_hop[j]
            path.append(self.ids[j])
        return tuple(path)


def build_mesh(nodes: Sequence[MeshNode], border_id: str, radio: MeshRadio,
               path_loss: Optional[LogDistanceModel] = None,
               max_hops: int = MAX_HOPS) -> MeshGraph:
    """Calcule les liens faisables et les routes les plus courtes vers la frontière."""
    if not 1 <= max_hops <= MAX_HOPS:
        raise ValueError(f"max_hops doit être compris entre 1 et {MAX_HOPS}")
    if not 1 <= len(nodes) <= MAX_NODES:
        raise ValueError(f"le réseau mesh compte au plus {MAX_NODES} passerelles")
    ids = [n.gateway_id for n in nodes]
    if len(set(ids)) != len(ids):
        raise ValueError("identifiants de passerelles en double")
    by_id = {n.gateway_id: n for n in nodes}
    if border_id not in by_id:
        raise ValueError("passerelle frontière inconnue")
    if not by_id[border_id].mesh_capable:
        raise ValueError("la passerelle frontière doit avoir une radio mesh")
    model = path_loss or LogDistanceModel(frequency_hz=MESH_BAND_HZ)

    n = len(nodes)
    rssi = (ctypes.c_double * (n * n))()
    capable = tuple(1 if x.mesh_capable else 0 for x in nodes)
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            if i == j:
                rssi[i * n + j] = float("-inf")
                continue
            d = max(((a.x_m - b.x_m) ** 2 + (a.y_m - b.y_m) ** 2) ** 0.5, 1.0)
            pl = model.path_loss_db(d)
            rssi[i * n + j] = a.tx_power_dbm + a.antenna_gain_dbi - pl + b.antenna_gain_dbi
    cap = (ctypes.c_uint8 * n)(*capable)
    nxt = (ctypes.c_int32 * n)()
    border = ids.index(border_id)
    _check(_LIB.lsim_mesh_routes(ctypes.byref(_c_radio(radio)), n, cap, rssi,
                                 border, max_hops, nxt))
    return MeshGraph(border_id=border_id, ids=tuple(ids), next_hop=tuple(nxt),
                     rssi=rssi, capable=capable, radio=radio,
                     _index={g: k for k, g in enumerate(ids)})


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


def forward_frames(frames: Sequence[MeshFrame], graph: MeshGraph,
                   radio: Optional[MeshRadio] = None) -> MeshResult:
    """Relais des trames saut par saut sur la bande mesh (calcul natif)."""
    radio = radio or graph.radio
    index = graph._index
    n = len(graph.ids)
    if len(frames) > 5_000_000:
        raise ValueError("trop de trames pour un seul calcul mesh")
    c_frames = (_CMeshFrame * len(frames))()
    for k, f in enumerate(frames):
        if f.rx_gateway_id not in index:
            raise ValueError(f"passerelle inconnue : {f.rx_gateway_id!r}")
        c_frames[k].frame_id = f.frame_id
        c_frames[k].rx_node = index[f.rx_gateway_id]
        c_frames[k].t_ns = f.t_ns
    c_out = (_CMeshDelivery * len(frames))()
    nxt = (ctypes.c_int32 * n)(*graph.next_hop)
    _check(_LIB.lsim_mesh_forward(
        ctypes.byref(_c_radio(radio)), n, graph.rssi, nxt, graph._index[graph.border_id],
        c_frames, len(frames), c_out))
    out: list[MeshDelivery] = []
    for k in range(len(frames)):
        d = c_out[k]
        out.append(MeshDelivery(
            frame_id=int(d.frame_id),
            delivered=bool(d.delivered),
            hops=int(d.hops),
            latency_ns=int(d.latency_ns) if d.delivered else None,
            loss=_LOSS_NAMES[d.loss],
        ))
    out.sort(key=lambda x: x.frame_id)
    return MeshResult(deliveries=out)

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
- collision : la plus forte survit si elle dépasse l'autre de `capture_db` ;
- suppression des doublons (par identifiant de trame) : une passerelle qui entend,
  avant son propre départ, un autre relais transmettre la même trame renonce à la
  sienne. Toute émission audible gêne les autres : l'écoute gratuite a un coût.

Sensibilité : tableau SX1280 « low power mode », CR 4/5, PER 1 %, 10 octets
(Semtech DS.SX1280-1 Rev 3.0, table 6-1), plus conservateur que le mode haute
sensibilité, dont seul le point SF12/203 kHz est publié.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Optional, Sequence

from lsim._native import LIB as _LIB
from lsim._native import _CMeshDelivery, _CMeshFrame, _CMeshHop, _CMeshRadio, _CMeshSummary
from lsim.lora import StatusError
from lsim.radio import LogDistanceModel

MAX_HOPS = 8
# Fenêtres de réception du dispositif après la fin de son émission (LoRaWAN, classe A).
RX1_DELAY_NS = 1_000_000_000
RX2_DELAY_NS = 2_000_000_000
# Enveloppe ChirpStack Gateway Mesh, ajoutée à la trame LoRaWAN : 14 o en montant, 15 o en
# descendant (documentation RAK « Gateway Mesh » et ChirpStack, protocole uplink).
MESH_ENVELOPE_UP_BYTES = 14
MESH_ENVELOPE_DOWN_BYTES = 15
# Acquittement seul (sans charge) : MHDR 1 + FHDR 7 + MIC 4 = 12 o de PHY.
DOWNLINK_ACK_PHY_BYTES = 12


def lorawan_phy_bytes(app_payload_bytes: int) -> int:
    """Taille PHY LoRaWAN (MHDR, FHDR 7 o, FPort, charge, MIC 4 o)."""
    if not 0 <= app_payload_bytes <= 242:
        raise ValueError("charge applicative hors domaine (0..242 octets)")
    return 13 + app_payload_bytes if app_payload_bytes > 0 else 12
MAX_NODES = 64          # kMaxGateways côté natif
MESH_BAND_HZ = 2_400_000_000
_BW_KHZ = (203, 406, 812, 1625)
_LOSS_NAMES = ("", "no_route", "half_duplex", "collision", "suppressed")
_COPY_STATES = ("forwarded", "suppressed", "border", "no_route")
MAX_FRAMES = 5_000_000  # kMaxFrames côté natif
_BUFFER_TOO_SMALL = 800 + 10  # mesh::Status::BufferTooSmall + LSIM_STATUS_MESH_BASE
_HOP_OUTCOMES = ("received", "lost_collision", "lost_half_duplex", "suppressed")


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

    spreading_factor: int = 9
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
    """Routes vers la frontière (`next_hop`), et vers toute autre passerelle capable (`route_row`).

    Les liens (rssi, capacités, sensibilité) ne dépendent pas de la destination : une seule
    matrice sert à toutes les routes, calculées par le natif et mises en cache.
    """

    border_id: str
    ids: tuple[str, ...]
    next_hop: tuple[int, ...]          # indice du saut suivant, -1 si aucune route
    rssi: ctypes.Array                 # rssi[i*n+j] : reçu en j, émis par i (dBm)
    capable: tuple[int, ...]
    radio: MeshRadio
    max_hops: int = MAX_HOPS
    _index: dict = field(default_factory=dict, repr=False)
    _routes: dict = field(default_factory=dict, repr=False)

    def route_row(self, dest_id: str) -> tuple[int, ...]:
        """Saut suivant de chaque passerelle vers `dest_id` (-1 si aucune route).

        Destination frontière : `next_hop`. Autre destination (relais) : route calculée par le
        natif avec la même matrice de liens et la même limite de sauts.
        """
        if dest_id == self.border_id:
            return self.next_hop
        if dest_id not in self._routes:
            n = len(self.ids)
            nxt = (ctypes.c_int32 * n)()
            cap = (ctypes.c_uint8 * n)(*self.capable)
            _check(_LIB.lsim_mesh_routes(ctypes.byref(_c_radio(self.radio)), n, cap, self.rssi,
                                         self._index[dest_id], self.max_hops, nxt))
            self._routes[dest_id] = tuple(nxt)
        return self._routes[dest_id]

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


# Sel du tirage de shadowing mesh : sépare ces tirages de ceux de l'accès (même graine).
MESH_SHADOW_SALT = 0x4D6573684C6E6B31  # « MeshLnk1 »


def pair_shadowing_db(seed: int, i: int, j: int, n: int, sigma_db: float) -> float:
    """Shadowing réciproque de la paire {i, j} (dB, même valeur dans les deux sens).

    Un tirage par paire : l'indice est min(i,j)*n + max(i,j), donc (i,j) et (j,i) partagent
    la valeur. Fonction pure ; sigma_db = 0 donne 0.
    """
    if sigma_db == 0.0:
        return 0.0
    a, b = (i, j) if i < j else (j, i)
    out = ctypes.c_double(0.0)
    _check(_LIB.lsim_shadowing_sample_db((seed ^ MESH_SHADOW_SALT) & (2**64 - 1),
                                         a * n + b, sigma_db, ctypes.byref(out)))
    return out.value


def build_mesh(nodes: Sequence[MeshNode], border_id: str, radio: MeshRadio,
               path_loss: Optional[LogDistanceModel] = None,
               max_hops: int = MAX_HOPS,
               path_loss_db: Optional[Sequence[float]] = None,
               shadowing_sigma_db: float = 0.0, shadowing_seed: int = 0) -> MeshGraph:
    """Calcule les liens faisables et les routes les plus courtes vers la frontière.

    Pertes de propagation : `path_loss_db` (matrice à plat n*n, calculée par le natif avec
    relief et obstacles) si fournie ; sinon le modèle `path_loss` (log-distance).
    `shadowing_sigma_db` > 0 : un tirage log-normal par paire de passerelles, identique dans
    les deux sens (liaison réciproque), déterministe pour `shadowing_seed`.
    """
    if not 0.0 <= shadowing_sigma_db <= 30.0:
        raise ValueError("shadowing_sigma_db doit être compris entre 0 et 30 dB")
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
    if path_loss_db is not None and len(path_loss_db) != n * n:
        raise ValueError("path_loss_db doit contenir n*n valeurs")
    rssi = (ctypes.c_double * (n * n))()
    capable = tuple(1 if x.mesh_capable else 0 for x in nodes)
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            if i == j:
                rssi[i * n + j] = float("-inf")
                continue
            if path_loss_db is not None:
                pl = float(path_loss_db[i * n + j])
            else:
                d = max(((a.x_m - b.x_m) ** 2 + (a.y_m - b.y_m) ** 2) ** 0.5, 1.0)
                pl = model.path_loss_db(d)
            rssi[i * n + j] = a.tx_power_dbm + a.antenna_gain_dbi - pl + b.antenna_gain_dbi
    if shadowing_sigma_db > 0.0:
        for i in range(n):
            for j in range(i + 1, n):
                s_db = pair_shadowing_db(shadowing_seed, i, j, n, shadowing_sigma_db)
                rssi[i * n + j] -= s_db
                rssi[j * n + i] -= s_db
    cap = (ctypes.c_uint8 * n)(*capable)
    nxt = (ctypes.c_int32 * n)()
    border = ids.index(border_id)
    _check(_LIB.lsim_mesh_routes(ctypes.byref(_c_radio(radio)), n, cap, rssi,
                                 border, max_hops, nxt))
    return MeshGraph(border_id=border_id, ids=tuple(ids), next_hop=tuple(nxt),
                     rssi=rssi, capable=capable, radio=radio, max_hops=max_hops,
                     _index={g: k for k, g in enumerate(ids)})


def downlink_window(latency_ns: int, hops: int, mesh_airtime_ns: int) -> str:
    """Fenêtre de descente atteignable pour une trame remise : « rx1 », « rx2 » ou « missed ».

    Modèle (borne optimiste) : la réponse part de la frontière dès réception ; elle
    redescend le chemin inverse, `hops` émissions mesh de `mesh_airtime_ns` chacune, et
    le relais l'émet vers le dispositif dès qu'elle est arrivée. `latency_ns` : durée de
    remontée jusqu'à la frontière, depuis la fin de l'émission du dispositif. Ni collision
    ni file d'attente sur le retour ne sont comptées.
    """
    arrival = latency_ns + hops * mesh_airtime_ns
    if arrival <= RX1_DELAY_NS:
        return "rx1"
    if arrival <= RX2_DELAY_NS:
        return "rx2"
    return "missed"


@dataclass(frozen=True)
class MeshFrame:
    frame_id: int
    rx_gateway_id: str   # passerelle qui a reçu la trame (accès, ou frontière pour une descente)
    t_ns: int            # fin de réception (accès), ou départ de la frontière (descente)
    payload_bytes: int = 32  # taille relayée : trame LoRaWAN + enveloppe mesh (0..255)
    # Destination : passerelle capable visée. None : la frontière du graphe (montant).
    dest_id: Optional[str] = None


@dataclass(frozen=True)
class MeshDelivery:
    """Une entrée par copie reçue à l'accès. `delivered`, `hops`, `latency_ns` et `loss`
    décrivent la trame (identique pour toutes ses copies) ; `copy_state` la copie."""

    frame_id: int
    delivered: bool
    hops: int                 # sauts de la copie livrée en premier ; 0 si non livrée
    latency_ns: Optional[int]
    loss: str = ""            # "" si livré ; sinon : no_route, half_duplex, collision, suppressed
    copy_state: str = ""      # sort de la copie reçue à l'accès : forwarded, suppressed, border, no_route


@dataclass(frozen=True)
class MeshHop:
    """Un saut mesh journalisé : émission d'un relais vers le saut prévu, ou copie supprimée.

    `t_start_ns`/`t_end_ns` : durée de l'émission ; pour une copie supprimée, les deux valent
    l'instant de la décision. `outcome` : received, lost_collision, lost_half_duplex, suppressed.
    """

    frame_id: int
    sender_id: str
    receiver_id: str
    t_start_ns: int
    t_end_ns: int
    outcome: str
    hop_index: int


@dataclass
class MeshResult:
    deliveries: list[MeshDelivery] = field(default_factory=list)
    transmissions: int = 0        # émissions mesh effectives (chaque saut compte)
    suppressed: int = 0           # copies abandonnées parce qu'un doublon avait été relayé
    lost_collision: int = 0       # sauts perdus par collision
    lost_half_duplex: int = 0     # sauts perdus : récepteur en émission
    hops: tuple[MeshHop, ...] = ()  # journal des sauts (seulement si demandé)

    @property
    def delivered(self) -> int:
        """Trames distinctes remises au LNS (une trame peut avoir plusieurs copies)."""
        return len({d.frame_id for d in self.deliveries if d.delivered})

    def count(self, loss: str) -> int:
        """Copies dont la trame a été perdue pour la raison `loss`."""
        return sum(1 for d in self.deliveries if d.loss == loss)


def forward_frames(frames: Sequence[MeshFrame], graph: MeshGraph,
                   radio: Optional[MeshRadio] = None,
                   suppress_duplicates: bool = True,
                   backoff_window_ns: int = 0,
                   with_hops: bool = False) -> MeshResult:
    """Relais des trames saut par saut sur la bande mesh (calcul natif).

    Chaque trame va vers sa destination (`dest_id`, la frontière par défaut). Les trames de
    destinations différentes partagent le temps d'antenne et la suppression des doublons : une
    seule passe, une même politique pour le montant et la descente.

    `suppress_duplicates=True` (défaut) : un relais n'émet la trame qu'une fois et
    renonce à sa copie s'il entend un autre relais la transmettre avant son départ.
    `False` : chaque copie reçue est relayée, comportement sans identifiant de trame.
    `backoff_window_ns` : chaque relais attend un délai déterministe dans [0, fenêtre)
    avant de transmettre une copie, pour laisser le temps d'entendre un autre relais.
    """
    if backoff_window_ns < 0:
        raise ValueError("backoff_window_ns doit être positif ou nul")
    radio = radio or graph.radio
    index = graph._index
    n = len(graph.ids)
    if len(frames) > MAX_FRAMES:
        raise ValueError("trop de trames pour un seul calcul mesh")
    border_id = graph.border_id
    dest_ids = [f.dest_id if f.dest_id is not None else border_id for f in frames]
    c_frames = (_CMeshFrame * len(frames))()
    c_dests = (ctypes.c_uint32 * len(frames))()
    for k, f in enumerate(frames):
        if f.rx_gateway_id not in index:
            raise ValueError(f"passerelle inconnue : {f.rx_gateway_id!r}")
        if dest_ids[k] not in index:
            raise ValueError(f"destination inconnue : {dest_ids[k]!r}")
        c_frames[k].frame_id = f.frame_id
        c_frames[k].rx_node = index[f.rx_gateway_id]
        if not 0 <= f.payload_bytes <= 255:
            raise ValueError("taille de trame mesh hors domaine (0..255)")
        c_frames[k].t_ns = f.t_ns
        c_frames[k].payload_bytes = f.payload_bytes
        c_dests[k] = index[dest_ids[k]]
    # Matrice des routes : une ligne par destination utilisée (les autres lignes restent -1).
    by_dest = (ctypes.c_int32 * (n * n))(*([-1] * (n * n)))
    for d in set(dest_ids):
        row = graph.route_row(d)
        base = index[d] * n
        for i in range(n):
            by_dest[base + i] = row[i]
    c_out = (_CMeshDelivery * len(frames))()
    c_sum = _CMeshSummary()
    cap = (ctypes.c_uint8 * n)(*graph.capable)
    head = (ctypes.byref(_c_radio(radio)), n, cap, graph.rssi, by_dest, c_dests,
            1 if suppress_duplicates else 0, backoff_window_ns, c_frames, len(frames), c_out,
            ctypes.byref(c_sum))
    hops: tuple[MeshHop, ...] = ()
    # Journal des sauts : toujours produit par le natif. Sans `with_hops`, tampon nul : le natif
    # ne renvoie que la taille (statut « tampon trop petit », ignoré ici).
    size = max(1024, 4 * len(frames)) if with_hops else 0
    while True:
        c_hops = (_CMeshHop * size)()
        c_count = ctypes.c_size_t(0)
        status = _LIB.lsim_mesh_forward_routed_log(*head, c_hops, size, ctypes.byref(c_count))
        if status != _BUFFER_TOO_SMALL or not with_hops:
            break
        size = int(c_count.value)
    if not (status == _BUFFER_TOO_SMALL and not with_hops):
        _check(status)
    if with_hops:
        hops = tuple(
            MeshHop(frame_id=int(h.frame_id), sender_id=graph.ids[h.sender],
                    receiver_id=graph.ids[h.receiver], t_start_ns=int(h.t_start_ns),
                    t_end_ns=int(h.t_end_ns), outcome=_HOP_OUTCOMES[h.outcome],
                    hop_index=int(h.hop_index))
            for h in c_hops[:c_count.value])
    out: list[MeshDelivery] = []
    for k in range(len(frames)):
        d = c_out[k]
        out.append(MeshDelivery(
            frame_id=int(d.frame_id),
            delivered=bool(d.delivered),
            hops=int(d.hops),
            latency_ns=int(d.latency_ns) if d.delivered else None,
            loss=_LOSS_NAMES[d.loss] if not d.delivered else "",
            copy_state=_COPY_STATES[d.copy_state],
        ))
    out.sort(key=lambda x: x.frame_id)
    return MeshResult(
        deliveries=out,
        transmissions=int(c_sum.transmissions),
        suppressed=int(c_sum.suppressed),
        lost_collision=int(c_sum.lost_collision),
        lost_half_duplex=int(c_sum.lost_half_duplex),
        hops=hops,
    )

"""Trace par transmission et événements du protocole, sur la même horloge que le moteur.

Le cœur natif produit une entrée par émission (début, fin, issue à la passerelle). Ce module
en dérive les événements de la couche protocole, avec les temporisations de la spécification :

- join-request : même issue que l'émission ; join-accept à fin + JOIN_ACCEPT_DELAY1 (5 s) ;
- uplink de données : issue de l'émission ; un uplink accepté par la passerelle ouvre une
  fenêtre RX1 à fin + RECEIVE_DELAY1 (1 s) ;
- downlink (un seul par uplink accepté, comme `lsim.uplink`) : si une charge est en file
  (`downlink_every`), sinon ACK seul si l'uplink est confirmé.

Modèle de la passerelle (demi-duplex, un émetteur) :
- elle n'émet qu'un downlink à la fois : un downlink qui tombe pendant un autre attend la fin de
  celui-ci. S'il ne peut partir qu'après la fenêtre RX1 du dispositif (1 s), il est perdu
  (`rx_window_missed`, issue `gateway_busy`), sans retransmission ;
- pendant une émission de downlink, elle ne reçoit pas : une trame montante qui la chevauche est
  perdue (issue `lost_gateway_busy`). Les émissions de downlink dépendent des uplinks reçus, et
  inversement : le calcul itère jusqu'à un point fixe, sinon il échoue (pas de résultat faux).
  La boucle s'arrête à `MAX_ITERATIONS_TRACE` (64) ; si l'état se répète à l'identique, le cycle est
  signalé immédiatement : une répétition exacte ne peut pas converger, quel que soit le nombre
  de tours supplémentaires.

Modèle du dispositif :
- demi-duplex : s'il émet à nouveau pendant sa fenêtre RX1, la fenêtre est manquée
  (`rx_window_missed`, issue `device_transmitting`) ;
- réception du downlink par réciprocité : RSSI descendant = RSSI montant - P_dispositif
  + P_passerelle + G_dispositif (le gain d'antenne passerelle s'annule). Reçu si ce RSSI atteint
  la sensibilité du débit RX1 du plan (référence SX1276, `lsim.radio`) plus
  `device_rx_offset_db` (écart du récepteur réel, à renseigner depuis sa fiche technique).

Limites assumées : une seule passerelle ; backhaul passerelle -> serveur et transmission du
join-accept par le serveur sans perte (issue `delivered`) ; les downlinks ne sont pas testés
contre les brouillages du dispositif hors de la passerelle elle-même.

Les dates sont en nanosecondes entières, issues du moteur, sans recalcul flottant.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Optional, Sequence

from lsim.gwmp_server import JOIN_ACCEPT_DELAY1_US
from lsim.lora import RadioConfig, time_on_air_ns
from lsim.plan import (RECEIVE_DELAY1_US, Plan, UnsupportedUplinkDataRateError,
                       get_plan)
from lsim.radio import receiver_sensitivity_dbm
from lsim.scenario import Scenario

if TYPE_CHECKING:  # annotations seulement : évite le cycle avec closed_loop / downlink_plan
    from lsim.closed_loop import MacByteAccounting, MacQueueCounters
from lsim.mesh import MESH_ENVELOPE_DOWN_BYTES, MESH_ENVELOPE_UP_BYTES
from lsim import mac as lsim_mac
from lsim.mac import DevStatusReq, DeviceTimeAns, DeviceTimeReq, LinkCheckAns, LinkCheckReq
from lsim import mac_plan
from lsim.mac_plan import MacSchedule, device_status_request_due, uplink_requests
from lsim.mesh_pass import mesh_pass
from lsim.simulator import (
    MAX_TRACE_RECORDS,
    Counters,
    DownlinkRule,
    GatewayLoad,
    TxRecord,
    simulate_multi_downlinks,
    simulate_uplinks_trace,
)

NS_PER_US = 1_000
RECEIVE_DELAY1_NS = RECEIVE_DELAY1_US * NS_PER_US
# RX2 s'ouvre une seconde après RX1 : RP002 §2.3, RECEIVE_DELAY2 = RECEIVE_DELAY1 + 1 s.
RECEIVE_DELAY2_NS = 2 * RECEIVE_DELAY1_NS
RX2_WINDOW_NS = 1_000_000_000       # durée de la fenêtre RX2 (même largeur que RX1)
JOIN_ACCEPT_DELAY1_NS = JOIN_ACCEPT_DELAY1_US * NS_PER_US
# Durée de la fenêtre RX1 du dispositif (hypothèse, 1 s).
RX1_WINDOW_NS = 1_000_000_000
# Borne des événements par run (contrat d'API : 200 000).
MAX_EVENTS = 200_000
# Trame downlink sans charge : MHDR (1) + DevAddr (4) + FCtrl (1) + FCnt (2) + MIC (4).
ACK_FRAME_BYTES = 12
# Trame downlink avec charge : ACK_FRAME_BYTES + FPort (1) + charge.
DATA_FRAME_OVERHEAD_BYTES = 13
# Join-accept sans CFList : MHDR (1) + AppNonce (3) + NetID (3) + DevAddr (4) + DLSettings (1)
# + RxDelay (1) + MIC (4).
JOIN_ACCEPT_BYTES = 17
# --- Motifs d'issue d'une fenêtre descendante (validation transverse, §24) ----------------
# Deux familles **disjointes**, jamais confondues (§24.4.1) : `capacite` — la fenêtre ne peut
# pas porter la trame, `fil > N` — et `temporel` — elle le peut, mais l'émetteur est occupé à
# l'ouverture. Un motif de capacité n'entraîne aucune occupation ; un motif temporel non plus,
# mais pour une raison différente, que la distinction a précisément pour objet de rendre visible.
MOTIF_PAYLOAD_TOO_LARGE = "payload_too_large"    # la charge applicative seule dépasse N
MOTIF_FOPTS_OVERFLOW = "fopts_overflow"          # charge ≤ N, mais charge + |FOpts| > N
MOTIF_RX2_CAPACITY = "rx2_capacity"              # RX1 échouée, RX2 ne peut pas porter la trame
MOTIF_NO_WINDOW_CAPACITY = "no_window_capacity"  # aucune fenêtre candidate ne le peut
MOTIF_WINDOW_MISSED = "window_missed"            # émetteur occupé à l'ouverture (indispo.)

MOTIFS_CAPACITE = (MOTIF_PAYLOAD_TOO_LARGE, MOTIF_FOPTS_OVERFLOW,
                   MOTIF_RX2_CAPACITY, MOTIF_NO_WINDOW_CAPACITY)
MOTIFS_TEMPOREL = (MOTIF_WINDOW_MISSED,)
# Borne de sécurité de la boucle à point fixe (uplinks <-> descentes), en itérations.
# Mesuré (D3.2, 120 configurations de référence, 2 000 dispositifs) : le point fixe est atteint
# en 9 à 21 itérations ; les 69 configurations qui échouaient avec l'ancienne borne de 12 en
# demandaient 13 à 21. 64 laisse une marge d'un facteur 3 sans changer une seule configuration
# déjà convergente (celles-ci s'arrêtent au même point fixe, au même tour).
MAX_ITERATIONS_TRACE = 64

_UPLINK_OUTCOME = {
    TxRecord.OUTCOME_LOST_SENSITIVITY: "lost_sensitivity",
    TxRecord.OUTCOME_LOST_COLLISION: "lost_collision",
    TxRecord.OUTCOME_RECEIVED: "received",
    TxRecord.OUTCOME_LOST_GATEWAY_BUSY: "lost_gateway_busy",
}
_HOP_OUTCOME = {
    TxRecord.OUTCOME_LOST_SENSITIVITY: "lost_sensitivity",
    TxRecord.OUTCOME_LOST_COLLISION: "lost_collision",
    TxRecord.OUTCOME_RECEIVED: "delivered",
    TxRecord.OUTCOME_LOST_GATEWAY_BUSY: "not_listened",
}


@dataclass(frozen=True)
class ProtocolOptions:
    """Comportement applicatif et paramètres de réception, hors moteur radio."""

    join: bool = False              # première émission de chaque dispositif = join-request
    confirmed_uplinks: bool = False  # uplinks de données confirmés (ACK attendu)
    downlink_every: int = 0         # 0 : aucune charge en file ; N : une charge par N uplinks acceptés
    downlink_payload_bytes: int = 10  # charge des downlinks de données (hypothèse)
    gateway_tx_power_dbm: float = 14.0    # puissance d'émission de la passerelle (downlink)
    device_antenna_gain_dbi: float = 0.0  # gain d'antenne du dispositif (réception downlink)
    device_rx_offset_db: float = 0.0      # écart de sensibilité du récepteur réel (0 = SX1276)
    # Repli RX2 des descentes. **Activé par défaut**, comme le repli du Join-Accept
    # (`lsim.join`, `rx2_fallback: bool = True`) : c'est le comportement d'un réseau réel, et
    # l'écart n'était pas justifié.
    #
    # Même à `True`, le repli ne s'applique qu'aux dispositifs dont la fenêtre RX2 est
    # réellement renseignée (`rx2_sf != 0` **et** `rx2_hz != 0`) — voir `_Job.rx2_disponible`.
    # Sans région déclarée, `rx2_hz == 0` : le repli est donc **inerte** sur tous les scénarios
    # qui n'ont pas de région, ce qui préserve les empreintes gelées.
    #
    # Le repli ne s'exerce jamais « à côté » de RX1 : il n'est demandé que par la réaction d'une
    # RX1 **non émise** (voir `_schedule_gateway`).
    #
    # `repr=False` : le `repr` de `ProtocolOptions` est une **clé** du dépôt de référence
    # (`scripts/mac_baseline_dump.py`), dont l'empreinte `ed126d7f…` est gelée. Y faire
    # apparaître le champ changerait l'empreinte sans changer un seul événement : la référence
    # perdrait sa valeur de détection. Elle continue donc de porter sur le comportement, ce que
    # vérifie `test_rx2_fallback_absent_du_repr` (la clé ne doit pas dépendre de ce champ).
    rx2_fallback: bool = field(default=True, repr=False)


@dataclass(frozen=True)
class DeviceRadio:
    """Paramètres radio d'un dispositif : fréquence, DR montant, RX1, RX2 et puissance.

    RX2 est le repli régional (`DLSettings`) : fréquence et débit **propres**, distincts de RX1.
    `rx2_hz = 0` signale l'absence de plan régional : la fenêtre RX2 n'est alors pas renseignée, et
    le débit de repli reste l'hypothèse du simulateur (SF12 BW125, valeur par défaut EU868).
    """

    freq_hz: int
    dr: Optional[int]        # None si aucun plan régional
    rx1_hz: int              # fréquence de la fenêtre RX1 (égale à freq_hz sans plan)
    tx_power_dbm: float = 14.0
    rx1_sf: int = 7          # SF du débit RX1 (récepteur du dispositif)
    rx1_bw_hz: int = 125_000
    rx2_hz: int = 0          # fréquence de la fenêtre RX2 (0 : non renseignée)
    rx2_sf: int = 12         # SF du débit RX2 (repli régional ; 12 = défaut EU868)
    # Charge utile maximale **N** de chaque fenêtre, pour le DR descendant réellement utilisé.
    # `None` = aucune contrainte applicable — sans plan régional il n'existe pas de N (§22.7) ;
    # ce n'est pas une dispense, c'est l'absence de la grandeur à comparer. Renseigné par
    # `_radio`, seul endroit où le plan est connu et où le DR peut être résolu sans ambiguïté.
    rx1_max_payload: Optional[int] = None
    rx2_max_payload: Optional[int] = None
    rx2_bw_hz: int = 125_000

    @property
    def rx2_disponible(self) -> bool:
        """La fenêtre de secours est-elle matériellement renseignée ?

        `rx2_hz == 0` : aucune fréquence régionale — on ne peut pas émettre, et la deviner
        serait inventer une valeur réglementaire. `rx2_sf == 0` : pas de fenêtre de secours.
        """
        return self.rx2_hz != 0 and self.rx2_sf != 0


@dataclass(frozen=True)
class HopEvent:
    from_id: str
    to_id: str
    t_ns: int
    freq_hz: int
    dr: Optional[int]
    rssi_dbm: Optional[float]
    outcome: str


@dataclass(frozen=True)
class ProtocolEvent:
    seq: int
    t_ns: int
    kind: str
    device_index: int
    gateway_index: int
    hops: tuple[HopEvent, ...]
    outcome: str


@dataclass(frozen=True)
class DevicePower:
    """Puissance d'émission d'un dispositif, telle que la boucle fermée l'a **appliquée**.

    `first_index` / `last_index` : index de puissance du premier et du dernier uplink. Un
    index plus haut est une puissance plus basse (`adr.cpp` : l'index monte tant qu'il
    reste de la marge). `step_db` est le pas du plan régional.

    La réduction vaut donc `(last_index - first_index) * step_db` décibels. C'est une
    **réduction**, et non une puissance absolue : la base est la puissance configurée du
    dispositif, pas la PIRE du plan — mesuré à 300 m, un capteur réglé sur 14 dBm émet à
    l'index 0 le RSSI de 14 dBm, et non celui de 16 dBm. Afficher « 16 dBm → 2 dBm »
    serait donc faux de 2 dB au départ, et le bas de l'échelle descend sous le minimum
    régional (0 dBm mesuré pour l'index 7 en EU868, dont le plan s'arrête à 2 dBm).
    """

    first_index: int
    last_index: int
    step_db: float

    @property
    def reduction_db(self) -> float:
        """Décibels retirés entre le premier et le dernier uplink (négatif si hausse)."""
        return (self.last_index - self.first_index) * self.step_db


@dataclass(frozen=True)
class TerminalChannels:
    """Canaux que le serveur a **laissés** au terminal à la fin du run.

    `dr_masks` : canal -> masque des débits DR0..DR7 (bit k = DRk admis sur ce canal).
    `enabled` : canaux actifs, sous-ensemble des canaux définis.

    Distinction qui compte, et qui est celle du moteur : un canal **défini** mais non
    **activé** existe dans la configuration du terminal sans servir à l'émission. Afficher
    l'un pour l'autre ferait croire à un plan de canaux qui n'est pas celui que la trame
    suivante va réellement emprunter.
    """

    dr_masks: Mapping[int, int]
    enabled: tuple[int, ...]


@dataclass(frozen=True)
class TraceRun:
    per_device: tuple[Counters, ...]
    totals: Counters
    gateway: GatewayLoad
    records: tuple[TxRecord, ...]
    events: tuple[ProtocolEvent, ...]
    gateway_tx: tuple[tuple[int, int], ...]  # émissions de la passerelle [début, fin) (ns)
    # Boucle fermée seulement (None sur le chemin historique) :
    mac_queue: Optional[MacQueueCounters] = None  # file MAC (commandes ponctuelles)
    mac_bytes: Optional[MacByteAccounting] = None  # octets réservés / émis / confirmés
    # Retransmissions seulement (None sinon) : détail des essais, des ACK et des doublons.
    retransmissions: Optional[object] = None
    # Boucle fermée seulement : puissance d'émission appliquée, par dispositif. Absente
    # ailleurs — le chemin historique ne décide d'aucune puissance, et recopier l'index de
    # départ ferait croire à une observation là où le moteur n'a rien commandé.
    device_power: Optional[Mapping[int, DevicePower]] = None
    # Boucle fermée seulement : canaux laissés au terminal, par dispositif. Absent ailleurs,
    # pour la même raison que la puissance : l'ABI v2 ne les porte pas, et les recopier
    # depuis la configuration de départ publierait un plan que le serveur n'a pas arrêté.
    device_channels: Optional[Mapping[int, TerminalChannels]] = None


@dataclass(frozen=True)
class _Job:
    """Réponse de la passerelle attendue pour une trame montante reçue."""

    record: int           # index dans la trace
    device: int
    kind: str             # join_accept | ack | downlink
    content: str          # issue si reçue : delivered | ack_only | data | data_ack
    t_open: int           # ouverture de la fenêtre RX1 du dispositif
    airtime_ns: int       # durée d'émission du downlink
    rx1_hz: int
    received: bool        # réception par le dispositif (réciprocité)
    device_missed: bool   # le dispositif émet pendant sa fenêtre RX1
    fopts: bytes = b""    # commandes MAC en FOpts du downlink (LinkCheckAns, DevStatusReq)
    link_margin: int = 0  # marge rapportée par LinkCheckAns (dB, si présente)
    carries_ds: bool = False  # le downlink porte DevStatusReq (réponse attendue si reçue)
    # Fenêtre de secours. RX2 n'est ni RX1 ni une répétition : fréquence et débit régionaux
    # propres, donc temps d'antenne différent — d'où `rx2_airtime_ns` calculé à part.
    rx2_hz: int = 0           # 0 : fréquence non renseignée (aucun plan régional)
    rx2_sf: int = 0           # 0 : aucun repli pour ce dispositif
    rx2_bw_hz: int = 0
    rx2_airtime_ns: int = 0   # 0 tant que `rx2_disponible` est faux
    device_missed_rx2: bool = False  # le dispositif émet pendant sa fenêtre RX2
    # --- Conformité de la charge (validation transverse, §24) -----------------------------
    # `charge_contrainte` est la grandeur comparée à N : **charge + |FOpts|**, et non la
    # trame entière. Rappel : N borne la charge utile (FRMPayload), M = N + 8 borne le
    # MACPayload, et PHYPayload = 13 + charge + |FOpts|. Comparer `fil` à N sous-utiliserait
    # la capacité de 13 octets et rejetterait des trames légales (§25.2.1).
    charge_contrainte: int = 0              # 0 hors descente applicative
    soumis_a_n: bool = False                # seules les descentes applicatives y sont soumises
    rx1_max_payload: Optional[int] = None   # N de RX1 ; None = inconnu (pas de plan régional)
    rx2_max_payload: Optional[int] = None   # N de RX2 ; None = inconnu

    @property
    def rx1_eligible(self) -> bool:
        """La fenêtre RX1 peut-elle porter la trame ? (R-N1 : validation par fenêtre.)"""
        if not self.soumis_a_n or self.rx1_max_payload is None:
            return True          # trames MAC, ou sans région : aucune contrainte applicable
        return self.charge_contrainte <= self.rx1_max_payload

    @property
    def rx2_eligible(self) -> bool:
        """La fenêtre RX2 peut-elle porter la trame ? Évaluée indépendamment de RX1."""
        if not self.soumis_a_n or self.rx2_max_payload is None:
            return True
        return self.charge_contrainte <= self.rx2_max_payload

    @property
    def rx2_disponible(self) -> bool:
        """Le repli RX2 est-il matériellement possible pour ce job ?

        Deux conditions, toutes deux nécessaires. `rx2_sf == 0` : le dispositif n'a pas de
        fenêtre de secours, il n'y a rien à replier. `rx2_hz == 0` : aucune fréquence
        régionale — on ne peut pas émettre sans fréquence, et la deviner serait inventer une
        valeur réglementaire. Le repli est donc **inerte** dans ce cas, ce qui est le
        comportement attendu tant que l'exposition régionale de RX2 n'est pas faite.
        """
        return self.rx2_sf != 0 and self.rx2_hz != 0

    @property
    def t_open_rx2(self) -> int:
        """Ouverture de la fenêtre RX2 : RECEIVE_DELAY2 après la fin de la montante."""
        return self.t_open + (RECEIVE_DELAY2_NS - RECEIVE_DELAY1_NS)


def _dev(i: int) -> str:
    return f"dev:{i}"


_DATR = re.compile(r"^SF(\d+)BW(\d+)$")


def _radio(plan: Optional[Plan], freq_hz: int, sf: int, tx_power_dbm: float,
           rx1_dr_offset: int = 0) -> DeviceRadio:
    """`rx1_dr_offset` : RX1DROffset du terminal (0 = réglage du serveur, valeur historique)."""
    if plan is None:
        return DeviceRadio(freq_hz=freq_hz, dr=None, rx1_hz=freq_hz, tx_power_dbm=tx_power_dbm,
                           rx1_sf=sf, rx1_bw_hz=125_000)
    dr = next((i for i, (s, bw, _) in enumerate(plan.dr_table()) if s == sf and bw == 125), None)
    if dr is None:
        # P1 : aucun DR montant pour ce SF. On refuse **avant la simulation** plutôt que de
        # retomber silencieusement sur le SF brut à 125 kHz, qui ignorerait le mappage
        # régional et produirait une chronologie ne correspondant à aucune région réelle.
        # Sans plan (pas de région), il n'y a rien à résoudre : ce cas reste licite.
        raise UnsupportedUplinkDataRateError(
            region=plan.name, spreading_factor=sf, bandwidth_hz=125_000,
            available=sorted({s for s, bw, _ in plan.dr_table() if bw == 125}))
    rx1_hz, rx1_sf, rx1_bw_hz = freq_hz, sf, 125_000
    try:
        ch = plan.channel_index(freq_hz / 1_000_000)
        rx1_mhz, rx1_datr = plan.rx1(dr, ch, rx1_dr_offset)
        rx1_hz = round(rx1_mhz * 1_000_000)
        m = _DATR.match(rx1_datr)
        if m is not None:
            rx1_sf, rx1_bw_hz = int(m.group(1)), int(m.group(2)) * 1000
    except ValueError:
        rx1_hz = freq_hz
    # RX2 : fréquence et débit du repli régional. Sans plan, ou si le plan ne les expose pas, on
    # garde l'hypothèse du simulateur (SF12 BW125) et une fréquence non renseignée.
    rx2_hz, rx2_sf, rx2_bw_hz = 0, 12, 125_000
    if plan is not None:
        try:
            freq2_hz, rx2_datr = plan.rx2()
            m2 = _DATR.match(rx2_datr)
            if m2 is not None:
                rx2_hz = int(freq2_hz)
                rx2_sf, rx2_bw_hz = int(m2.group(1)), int(m2.group(2)) * 1000
        except (ValueError, KeyError, IndexError):
            rx2_hz, rx2_sf, rx2_bw_hz = 0, 12, 125_000
    # N des deux fenêtres, dérivé du SF et de la bande **réellement** émis — donc après
    # résolution du canal pour RX1 — et non du seul DR montant. Chaque fenêtre est évaluée
    # pour elle-même (R-N1) ; RX2 sur ses propres paramètres, jamais sur ceux de l'uplink.
    def _n(sf: int, bw_hz: int) -> Optional[int]:
        if sf == 0 or bw_hz == 0:
            return None
        try:
            return plan.max_frm_payload(plan.dr_of_downlink_datr(f"SF{sf}BW{bw_hz // 1000}"))
        except (ValueError, KeyError, IndexError):
            return None

    return DeviceRadio(freq_hz=freq_hz, dr=dr, rx1_hz=rx1_hz, tx_power_dbm=tx_power_dbm,
                       rx1_sf=rx1_sf, rx1_bw_hz=rx1_bw_hz,
                       rx2_hz=rx2_hz, rx2_sf=rx2_sf, rx2_bw_hz=rx2_bw_hz,
                       rx1_max_payload=_n(rx1_sf, rx1_bw_hz),
                       # RX2 non renseignée (`rx2_hz == 0`) : il n'y a pas de fenêtre de
                       # secours, donc pas de N de repli — et rien à comparer.
                       rx2_max_payload=_n(rx2_sf, rx2_bw_hz) if rx2_hz else None)


def _rx2_spreading_factor(scenario: Scenario) -> int:
    """SF du repli RX2 des descentes : celui du plan régional des groupes (12 sans plan, valeur
    EU868 par défaut). Un seul SF par scénario : des régions aux RX2 différentes sont refusées."""
    sfs = set()
    for g in scenario.model.groups:
        if g.region is None:
            continue
        try:
            sfs.add(get_plan(g.region).rx2_spreading_factor())
        except ValueError:
            continue
    if len(sfs) > 1:
        raise ValueError("descentes : les régions du scénario ont des RX2 différentes "
                         f"(SF {sorted(sfs)}) ; un seul débit de repli par scénario")
    return sfs.pop() if sfs else 12


def device_radios(scenario: Scenario) -> tuple[DeviceRadio, ...]:
    """Paramètres radio de chaque dispositif, dans l'ordre de `Scenario.deploy`."""
    _devices, group_of, _ = scenario.deploy()
    by_name = {g.name: g for g in scenario.model.groups}
    radios = []
    for name in group_of:
        g = by_name[name]
        plan: Optional[Plan] = None
        if g.region is not None:
            try:
                plan = get_plan(g.region)
            except ValueError:
                plan = None
        radios.append(_radio(plan, g.channel_freq_hz, g.spreading_factor, g.tx_power_dbm,
                             g.rx1_dr_offset))
    return tuple(radios)


def _table_rx2(radios) -> tuple[DeviceRx2, ...]:
    """Table RX2 du cœur, une entrée par dispositif, à partir des radios du scénario.

    C'est le chaînon qui manquait (I3) : les profils régionaux exposent RX2 depuis toujours, et
    `device_radios` remplit déjà `DeviceRadio.rx2_*` — mais rien n'en faisait une table pour le
    cœur. Sans région, `rx2_hz = 0` : la table est alors inerte, le repli ne se produit pas, et
    aucun scénario historique ne change.
    """
    from lsim.downlink_plan import DeviceRx2

    return tuple(DeviceRx2(rx2_hz=r.rx2_hz, rx2_sf=r.rx2_sf, rx2_bw_hz=r.rx2_bw_hz)
                 for r in radios)


def downlink_phy(radio: DeviceRadio, window: str = "rx1") -> tuple[int, int, int]:
    """`(fréquence, SF, largeur de bande)` de la fenêtre dans laquelle la descente est émise.

    RX2 n'est **pas** RX1 : c'est le repli régional, avec sa propre fréquence et son propre débit
    (`DLSettings`). Une descente émise en RX2 au SF12 occupe l'émetteur bien plus longtemps que la
    même trame en RX1 au SF7 — le temps d'antenne doit donc suivre la fenêtre réellement émise.
    `window` vaut `rx1`, `rx2` ou `replay` ; un rejeu réémet la **même** trame, donc au débit de la
    fenêtre qui l'a portée (RX1 par défaut).
    """
    if window == "rx2":
        # Largeur non renseignée : RX2 reprend celle de RX1, comme le cœur (`valid_rx2`, ABI v2).
        # Sans cela, `2 ** sf / 0` lèverait au lieu de produire un temps d'antenne.
        return radio.rx2_hz, radio.rx2_sf, radio.rx2_bw_hz or radio.rx1_bw_hz
    return radio.rx1_hz, radio.rx1_sf, radio.rx1_bw_hz


def _valider_rx2(radio: DeviceRadio, device: int) -> None:
    """Bornes de RX2, identiques à `valid_rx2()` du cœur (ABI v2) : refuser plutôt que calculer faux.

    `rx2_sf = 0` et `rx2_bw_hz = 0` sont des valeurs **admissibles** (aucun repli ; largeur reprise
    de RX1), pas des erreurs — c'est l'absence de valeur, et elle est documentée.
    """
    if radio.rx2_hz < 0:
        raise ValueError(f"dispositif {device} : rx2_hz négatif ({radio.rx2_hz})")
    if radio.rx2_sf != 0 and not 7 <= radio.rx2_sf <= 12:
        raise ValueError(f"dispositif {device} : rx2_sf hors 7..12 ou 0 ({radio.rx2_sf})")
    if radio.rx2_bw_hz != 0 and radio.rx2_bw_hz not in (125_000, 250_000, 500_000):
        raise ValueError(f"dispositif {device} : rx2_bw_hz hors {{0, 125k, 250k, 500k}} "
                         f"({radio.rx2_bw_hz})")


def _downlink_airtime_ns(radio: DeviceRadio, payload_bytes: int, window: str = "rx1") -> int:
    """Temps d'antenne d'un downlink, au débit de la fenêtre émise (CR 4/5, en-tête, sans CRC)."""
    _freq, sf, bw = downlink_phy(radio, window)
    symbol_s = (2 ** sf) / bw
    config = RadioConfig(spreading_factor=sf, bandwidth_hz=bw, coding_rate=1, crc_on=False,
                         explicit_header=True, low_data_rate_optimize=symbol_s > 0.016)
    return time_on_air_ns(config, payload_bytes)


def _rssi_descendant(r: TxRecord, radio: DeviceRadio, options: ProtocolOptions) -> float:
    """Réciprocité : RSSI descendant = RSSI montant - P_dev + P_gw + G_dev."""
    return (r.rssi_dbm - radio.tx_power_dbm + options.gateway_tx_power_dbm
            + options.device_antenna_gain_dbi)


def _seuil_dispositif(radio: DeviceRadio, options: ProtocolOptions, en_rx2: bool = False) -> float:
    """Seuil de sensibilité du récepteur, dans la fenêtre réellement émise.

    Le seuil dépend du débit de la fenêtre, et RX2 n'a pas celui de RX1 : au SF12BW125 il est
    meilleur d'une quinzaine de dB qu'au SF7BW125. Évaluer une descente émise en RX2 avec le
    seuil de RX1 la déclarerait perdue alors que le dispositif l'entend — la parité entre les
    deux moteurs ne dit rien de cette erreur, ils la commettaient tous les deux.
    """
    if en_rx2 and radio.rx2_disponible:
        sf, bw = radio.rx2_sf, (radio.rx2_bw_hz or radio.rx1_bw_hz)
    else:
        sf, bw = radio.rx1_sf, radio.rx1_bw_hz
    return receiver_sensitivity_dbm(sf, bw) + options.device_rx_offset_db


def _duree_emise(job: "_Job", en_rx2: bool) -> int:
    """Durée d'antenne de la fenêtre réellement émise, pas celle de RX1."""
    return job.rx2_airtime_ns if en_rx2 else job.airtime_ns


def _received_by_device(r: TxRecord, radio: DeviceRadio, options: ProtocolOptions,
                        en_rx2: bool = False) -> bool:
    """Le dispositif entend-il la descente, compte tenu de la fenêtre réellement émise ?

    `en_rx2` : la descente a été repliée en RX2. Sans lui (ou à `False`), le seuil est celui de
    RX1 — comportement d'avant I3, conservé pour les appelants qui ne savent pas encore quelle
    fenêtre a abouti.
    """
    return _rssi_descendant(r, radio, options) >= _seuil_dispositif(radio, options, en_rx2)


def _join_roles(records: Sequence[TxRecord], joined: dict[int, int],
                options: ProtocolOptions) -> list[bool]:
    """Rôle de chaque émission : join-request tant que le dispositif n'a pas reçu son join-accept.

    `joined[d]` : instant (ns) où le join-accept de d est entièrement reçu (fin de transmission).
    Une émission démarrée avant cet instant est une join-request, sinon une donnée. Identique au
    multi (`engine.cpp`, `joined_at`).
    """
    if not options.join:
        return [False] * len(records)
    return [not (r.device_index in joined and r.start_ns >= joined[r.device_index])
            for r in records]


def _joined_times(jobs: Sequence[_Job], starts: Sequence[Optional[int]],
                  fenetres: Optional[Sequence[Optional[str]]] = None,
                  records: Optional[Sequence[TxRecord]] = None,
                  radios: Optional[Sequence[DeviceRadio]] = None,
                  options: Optional[ProtocolOptions] = None) -> dict[int, int]:
    """Instant de réception complète du premier join-accept délivré, par dispositif.

    La durée et la sensibilité sont celles de la fenêtre **réellement émise** (`fenetres`) : un
    join-accept replié en RX2 finit plus tard et s'entend de plus loin. Sans `fenetres`, on
    retombe sur RX1 — comportement d'avant I3.
    """
    out: dict[int, int] = {}
    for k, job in enumerate(jobs):
        start = starts[k]
        if job.kind != "join_accept" or start is None or job.device_missed:
            continue
        if not _recu_job(job, k, fenetres, records, radios, options):
            continue
        end = start + _duree_emise(job, bool(fenetres) and fenetres[k] == "rx2")
        out[job.device] = min(out.get(job.device, end), end)
    return out


def _recu_job(job: "_Job", k: int,
              fenetres: Optional[Sequence[Optional[str]]],
              records: Optional[Sequence[TxRecord]],
              radios: Optional[Sequence[DeviceRadio]],
              options: Optional[ProtocolOptions]) -> bool:
    """Sensibilité d'un job, évaluée sur la fenêtre réellement émise.

    Retombe sur `job.received` (seuil RX1) quand l'appelant ne fournit pas la fenêtre ou la
    trace — c'est le cas de tous les appelants d'avant I3.
    """
    if fenetres is None or records is None or radios is None or options is None:
        return job.received
    en_rx2 = fenetres[k] == "rx2"
    return _received_by_device(records[job.record], radios[job.device], options, en_rx2)


_MAC_NAME = {LinkCheckReq: "LinkCheckReq", DevStatusReq: "DevStatusReq", DeviceTimeReq: "DeviceTimeReq"}


def _mac_ranks(records: Sequence[TxRecord]) -> list[int]:
    """Rang 1-based de chaque émission parmi les émissions de son dispositif (ordre de trace)."""
    count: dict[int, int] = defaultdict(int)
    ranks = []
    for r in records:
        count[r.device_index] += 1
        ranks.append(count[r.device_index])
    return ranks


def _link_margin_db(r: TxRecord, installation_db: int) -> int:
    """Marge rapportée par LinkCheckAns : RSSI montant - sensibilité de réception (SX1276, 125 kHz,
    SF de l'émission) - marge d'installation, en dB entiers par défaut, bornée à 0..254.
    Indicative : c'est la marge au-dessus du seuil de perte du simulateur, pas la marge SNR
    normative."""
    margin = math.floor(r.rssi_dbm - receiver_sensitivity_dbm(r.spreading_factor, 125_000)
                        - installation_db)
    return max(0, min(254, margin))


def _downlink_jobs(records: Sequence[TxRecord], radios: Sequence[DeviceRadio],
                   options: ProtocolOptions, roles: Sequence[bool],
                   mac: Optional[MacSchedule] = None) -> list[_Job]:
    """Une réponse attendue par uplink reçu, dans l'ordre de la trace (un seul downlink par uplink).

    Avec `mac` :
    - un LinkCheckReq reçu est acquitté par un LinkCheckAns (downlink dédié s'il n'y en a pas) ;
    - un uplink reçu de rang multiple de `device_status_every` porte une DevStatusReq (downlink
      dédié s'il n'y en a pas). Elle est décidée par le rang, pas par le dispositif.
    Les FOpts allongent la trame, donc le temps d'antenne du downlink.
    """
    if options.downlink_every < 0:
        raise ValueError("downlink_every doit être positif ou nul")
    if not 0 <= options.downlink_payload_bytes <= 242:
        raise ValueError("downlink_payload_bytes doit être compris entre 0 et 242")

    by_device: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        by_device[r.device_index].append(i)
    next_start: dict[int, int] = {}
    for idxs in by_device.values():
        for a, b in zip(idxs, idxs[1:]):
            next_start[a] = records[b].start_ns

    ranks = _mac_ranks(records)
    jobs: list[_Job] = []
    accepted: dict[int, int] = defaultdict(int)
    for i, r in enumerate(records):
        d = r.device_index
        radio = radios[d]
        is_join = roles[i]
        if r.outcome != TxRecord.OUTCOME_RECEIVED:
            continue

        margin: Optional[int] = None
        carries_ds = False
        if is_join:
            t_open = r.end_ns + JOIN_ACCEPT_DELAY1_NS
            kind, content = "join_accept", "delivered"
            base = JOIN_ACCEPT_BYTES
            fopts = b""
        else:
            accepted[d] += 1
            wants_answer = mac is not None and LinkCheckReq() in uplink_requests(mac, ranks[i])
            wants_time = mac is not None and DeviceTimeReq() in uplink_requests(mac, ranks[i])
            carries_ds = mac is not None and device_status_request_due(mac, ranks[i])
            if wants_answer:
                margin = _link_margin_db(r, mac.link_margin_installation_db)
            queued = options.downlink_every > 0 and accepted[d] % options.downlink_every == 0
            if queued:
                kind = "downlink"
                content = "data_ack" if options.confirmed_uplinks else "data"
                base = DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes
            elif options.confirmed_uplinks:
                kind, content = "ack", "ack_only"
                base = ACK_FRAME_BYTES
            elif wants_answer or wants_time:
                kind, content = "mac_answer", "delivered"
                base = ACK_FRAME_BYTES
            elif carries_ds:
                kind, content = "downlink", "delivered"  # downlink MAC seul
                base = ACK_FRAME_BYTES
            else:
                continue
            t_open = r.end_ns + RECEIVE_DELAY1_NS
            # DeviceTimeAns : heure GPS au début de la fenêtre RX1 (époque GPS en t = 0 de la simulation).
            fopts = _downlink_fopts(margin, carries_ds,
                                    device_time_ns=t_open if wants_time else None)
        # Les descentes de données sont émises dans la fenêtre RX1 du dispositif.
        airtime = _downlink_airtime_ns(radio, base + len(fopts), "rx1")
        # Le repli est **opt-in** : à `rx2_fallback=False` on ne valide ni ne calcule rien, ce qui
        # reproduit exactement le comportement d'avant I2 (et celui du cœur, qui ne replie pas).
        # Actif, on valide d'abord — mêmes bornes que `valid_rx2()` côté C++ — car un SF hors
        # bornes donnerait un temps d'antenne faux plutôt qu'une erreur.
        repli = False
        if options.rx2_fallback:
            _valider_rx2(radio, d)
            # Sans fréquence régionale il n'y a rien à émettre, et le temps d'antenne RX2
            # (SF12 le plus souvent) n'a pas à être calculé.
            repli = radio.rx2_hz != 0 and radio.rx2_sf != 0
        airtime_rx2 = (_downlink_airtime_ns(radio, base + len(fopts), "rx2") if repli else 0)

        nxt = next_start.get(i)
        ouverture_rx2 = t_open + (RECEIVE_DELAY2_NS - RECEIVE_DELAY1_NS)
        # Seules les descentes **applicatives** sont soumises à N. Les trames MAC (ack,
        # mac_answer, downlink MAC seul) et le Join-Accept gardent leurs règles propres et
        # ne sont jamais refusés pour dépassement (§24.4.2, garde-fou 14).
        soumis_a_n = kind == "downlink" and content in ("data", "data_ack")
        jobs.append(_Job(
            record=i, device=d, kind=kind, content=content, t_open=t_open, airtime_ns=airtime,
            rx1_hz=radio.rx1_hz,
            received=_received_by_device(r, radio, options),
            device_missed=nxt is not None and nxt < t_open + RX1_WINDOW_NS,
            fopts=fopts, link_margin=margin or 0, carries_ds=carries_ds,
            rx2_hz=radio.rx2_hz, rx2_sf=radio.rx2_sf, rx2_bw_hz=radio.rx2_bw_hz,
            rx2_airtime_ns=airtime_rx2,
            device_missed_rx2=nxt is not None and nxt < ouverture_rx2 + RX2_WINDOW_NS,
            charge_contrainte=(options.downlink_payload_bytes + len(fopts)) if soumis_a_n else 0,
            soumis_a_n=soumis_a_n,
            rx1_max_payload=radio.rx1_max_payload, rx2_max_payload=radio.rx2_max_payload,
        ))
    return jobs


def _downlink_fopts(margin: Optional[int], carries_ds: bool,
                    device_time_ns: Optional[int] = None) -> bytes:
    """FOpts d'un downlink : LinkCheckAns (si `margin` n'est pas None), DevStatusReq (si
    `carries_ds`), DeviceTimeAns (si `device_time_ns` n'est pas None : heure GPS, époque en t = 0).
    Ordre CID croissant (LinkCheckAns 0x02, DevStatusReq 0x06, DeviceTimeAns 0x0D) ; jamais
    tronqué (15 octets au plus)."""
    cmds: list = []
    if margin is not None:
        cmds.append(LinkCheckAns(margin, 1))
    if carries_ds:
        cmds.append(DevStatusReq())
    if device_time_ns is not None:
        cmds.append(DeviceTimeAns(seconds=device_time_ns // 1_000_000_000,
                                  fraction=(device_time_ns % 1_000_000_000) * 256 // 1_000_000_000))
    fopts = b""
    for cmd in cmds:
        fopts = lsim_mac.append_fopts(fopts, cmd)
    return fopts


def _schedule_gateway(jobs: Sequence[_Job],
                     options: Optional[ProtocolOptions] = None,
                     ) -> tuple[list[Optional[int]], list[Optional[str]], list[tuple[int, int]]]:
    """Sérialise les downlinks sur la passerelle (un émetteur).

    Enveloppe de compatibilité : le contrat de retour à trois valeurs est préservé à
    l'identique pour la trentaine d'appelants existants — l'un d'eux compare le tuple
    entier. Les motifs sont exposés par `_schedule_gateway_with_motifs`.
    """
    debuts, fenetres, occupation, _motifs = _schedule_gateway_with_motifs(jobs, options)
    return debuts, fenetres, occupation


def _schedule_gateway_with_motifs(
        jobs: Sequence[_Job],
        options: Optional[ProtocolOptions] = None,
) -> tuple[list[Optional[int]], list[Optional[str]], list[tuple[int, int]],
           list[Optional[str]]]:
    """Sérialise les downlinks **et** rapporte le motif d'issue de chaque job.

    Retourne `(début par job ou None si aucune fenêtre n'a abouti, fenêtre réellement émise —
    `"rx1"`, `"rx2"` ou None, intervalles d'émission, motif d'issue)`.

    Le motif renseigne **tout** job non émis, et distingue deux familles disjointes
    (§24.4.1) : `capacite` — la fenêtre ne peut pas porter la trame — et `temporel` — elle
    le peut, mais l'émetteur est occupé à l'ouverture.

    L'émetteur est celui de `lsim.arbitre.GatewayArbiter`, partagé avec les Join-Accept et la
    couche MAC : une seule file, `début = max(ouverture, occupé_jusqu'à)`, abandon si le
    placement tombe hors de la fenêtre du dispositif. La règle est celle du planificateur C++
    au bit près (parité : `tests/test_downlink_plan_parity.py`).

    **Repli RX2 (I2).** RX1 reste prioritaire : RX2 n'est demandée que par la réaction d'une RX1
    **non émise**, jamais à côté ni en double. Il est opt-in (`options.rx2_fallback`) et ne
    s'applique qu'aux jobs dont la fenêtre de secours est réellement renseignée
    (`job.rx2_disponible`) : sans fréquence régionale il n'y a rien à émettre, et sans SF il n'y a
    pas de fenêtre. Le repli porte la fréquence, le SF et la bande passante de RX2 — donc un temps
    d'antenne différent, qui est celui réservé à l'émetteur. Une seule émission par descente : la
    réaction RX2 ne redemande rien.

    Sans `options` (ou `rx2_fallback=False`), le comportement est celui d'avant I2, à
    l'identique : la file ne contient que des demandes RX1.
    """
    from lsim.arbitre import EXACTE, EmissionRequest, GatewayArbiter

    repli_actif = options is not None and options.rx2_fallback
    # U0.3 / A6 : la descente part **exactement** à l'ouverture de RX1 ou de RX2, et non à la
    # libération de l'émetteur. C'est la règle du `RadioScheduler` du cœur, dont cet arbitre est
    # l'oracle de parité — les deux doivent appliquer la même formule.
    arbitre = GatewayArbiter(regle_placement=EXACTE)
    starts: list[Optional[int]] = [None] * len(jobs)
    fenetres: list[Optional[str]] = [None] * len(jobs)
    motifs: list[Optional[str]] = [None] * len(jobs)

    def fenetre(k: int, job: _Job, rx2: bool) -> EmissionRequest:
        if rx2:
            t2 = job.t_open_rx2
            return EmissionRequest(label=job.kind, device=job.device, ready_ns=t2,
                                   freq_hz=job.rx2_hz, duration_ns=job.rx2_airtime_ns,
                                   window=(t2, t2 + RX2_WINDOW_NS))
        return EmissionRequest(label=job.kind, device=job.device, ready_ns=job.t_open,
                               freq_hz=job.rx1_hz, duration_ns=job.airtime_ns,
                               window=(job.t_open, job.t_open + RX1_WINDOW_NS))

    def apres(k: int, rx2: bool):
        """Réaction d'un placement : retient l'émission, ou demande la fenêtre de secours.

        **R-N3.** L'inéligibilité d'une fenêtre ne clôt pas le parcours : RX2 reste
        examinable quand RX1 n'a pas abouti, et réciproquement. Seule une fenêtre
        inéligible n'est **jamais réservée** (R-N2) — elle ne fait l'objet d'aucune demande.

        **`condition` n'est pas utilisé** pour l'éligibilité : une `condition` fausse
        produit `NOT_NEEDED` et **supprime la réaction** (`arbitre.py`), ce qui
        désactiverait le repli. Le filtrage est donc fait ici, en amont du dépôt.
        """
        def reagir(emission, deposer) -> None:
            if emission.emitted:
                starts[k] = emission.start_ns
                fenetres[k] = "rx2" if rx2 else "rx1"
                return
            if rx2 or not repli_actif or not jobs[k].rx2_disponible:
                # Fenêtre manquée pour cause d'occupation : famille `temporel`.
                motifs[k] = MOTIF_WINDOW_MISSED
                return
            if not jobs[k].rx2_eligible:
                # R-N2 : aucune demande déposée, donc aucune occupation. Famille `capacite`.
                motifs[k] = MOTIF_RX2_CAPACITY
                return
            # RX1 n'a pas abouti — seconde fenêtre, une seule fois, avec ses propres paramètres.
            deposer(fenetre(k, jobs[k], True), ensuite=apres(k, True))
        return reagir

    for k, job in enumerate(jobs):
        if job.rx1_eligible:
            arbitre.demand(fenetre(k, job, False), ensuite=apres(k, False))
        elif job.rx2_eligible and repli_actif and job.rx2_disponible:
            # R-N1/R-N3 : RX1 ne peut pas porter la trame — elle n'est ni réservée ni émise —
            # mais le terminal ouvre RX2 comme le protocole le prévoit, et RX2 est examinée.
            arbitre.demand(fenetre(k, job, True), ensuite=apres(k, True))
        else:
            motifs[k] = MOTIF_NO_WINDOW_CAPACITY
    arbitre.resolve()
    return starts, fenetres, list(arbitre.occupation), motifs


def _events(records: Sequence[TxRecord], radios: Sequence[DeviceRadio], jobs: Sequence[_Job],
            starts: Sequence[Optional[int]], roles: Sequence[bool],
            mac: Optional[MacSchedule] = None,
            fenetres: Optional[Sequence[Optional[str]]] = None,
            options: Optional[ProtocolOptions] = None) -> tuple[ProtocolEvent, ...]:
    """Événements dans l'ordre temporel, à partir de la trace et de la planification.

    `fenetres` : fenêtre réellement émise par job (`"rx1"`, `"rx2"` ou None). Sans elle, toutes
    les descentes sont rapportées en RX1 — comportement d'avant I2.

    `options` : nécessaire pour évaluer la sensibilité **dans la fenêtre émise**. Sans lui, le
    seuil reste celui de RX1 (comportement d'avant I3) : `job.received`, calculé à la
    construction des jobs, avant que la fenêtre soit connue.
    """
    pending: list[tuple[int, int, str, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, tuple(hops), outcome))

    job_of = {job.record: k for k, job in enumerate(jobs)}
    ranks = _mac_ranks(records)
    # Réception par job, seuillée dans la fenêtre réellement émise. Calculée ici, une fois la
    # fenêtre connue : à la construction des jobs on ne sait pas encore si RX1 aboutira.
    if options is None:
        recu = [job.received for job in jobs]
    else:
        recu = [_received_by_device(records[job.record], radios[job.device], options,
                                    bool(fenetres) and fenetres[k] == "rx2")
                for k, job in enumerate(jobs)]
    # DevStatusAns : émise dans l'uplink suivant une DevStatusReq reçue. Confirmée seulement si
    # cet uplink est lui-même reçu par la passerelle ; sinon elle n'apparaît pas dans la trace.
    next_of: dict[int, int] = {}
    last_of: dict[int, int] = {}
    for i, r in enumerate(records):
        prev = last_of.get(r.device_index)
        if prev is not None:
            next_of[prev] = i
        last_of[r.device_index] = i
    ds_answer_at: set[int] = set()
    for k, job in enumerate(jobs):
        if not job.carries_ds or starts[k] is None or job.device_missed or not recu[k]:
            continue
        j = next_of.get(job.record)
        if j is not None and not roles[j] and records[j].outcome == TxRecord.OUTCOME_RECEIVED:
            ds_answer_at.add(j)
    for i, r in enumerate(records):
        d = r.device_index
        radio = radios[d]
        is_join = roles[i]
        hops = [HopEvent(_dev(d), "gw:0", r.start_ns, radio.freq_hz, radio.dr, r.rssi_dbm,
                         _HOP_OUTCOME[r.outcome])]
        if r.outcome == TxRecord.OUTCOME_RECEIVED:
            hops.append(HopEvent("gw:0", "ns", r.end_ns, radio.freq_hz, radio.dr, None,
                                 "delivered"))
        add(r.start_ns, "join_request" if is_join else "uplink", d, hops,
            _UPLINK_OUTCOME[r.outcome])
        if mac is not None and not is_join:
            for cmd in uplink_requests(mac, ranks[i]):
                # Annotation : la trame est déjà dessinée par l'événement uplink ; pas de saut dupliqué.
                add(r.start_ns, "mac_request", d, [], _MAC_NAME[type(cmd)])
        if i in ds_answer_at:
            add(r.start_ns, "mac_answer", d, [], "DevStatusAns")

        k = job_of.get(i)
        if k is None:
            continue
        job = jobs[k]
        start = starts[k]
        # Fenêtre réellement émise : la fréquence du saut descendant est celle de cette fenêtre,
        # pas systématiquement celle de RX1. Une descente repliée en RX2 n'est pas sur la même
        # fréquence — la rapporter en RX1 serait faux, et trompeur pour le rapport cyclique.
        en_rx2 = fenetres is not None and fenetres[k] == "rx2"
        freq_dl = job.rx2_hz if en_rx2 else job.rx1_hz
        # Le dispositif peut émettre pendant l'une fenêtre et pas l'autre : RX2 s'ouvre une
        # seconde plus tard, une montante courte n'a pas fini de la masquer.
        manquee = job.device_missed_rx2 if en_rx2 else job.device_missed
        if start is None:
            hop = HopEvent("gw:0", _dev(d), job.t_open, freq_dl, None, None, "not_listened")
            add(job.t_open, "rx_window_missed", d, [hop], "gateway_busy")
            continue
        if manquee:
            hop = HopEvent("gw:0", _dev(d), start, freq_dl, None, None, "not_listened")
            add(job.t_open, "rx_window_missed", d, [hop], "device_transmitting")
            continue
        ok = recu[k]
        down_hop = HopEvent("gw:0", _dev(d), start, freq_dl, None, None,
                            "delivered" if ok else "lost_sensitivity")
        if job.kind == "join_accept":
            down = [HopEvent("ns", "gw:0", start, freq_dl, None, None, "delivered"), down_hop]
        else:
            down = [down_hop]
        add(start, job.kind, d, down, job.content if ok else "lost_sensitivity")
        # Commandes MAC portées par un downlink reçu. Un job `mac_answer` est déjà l'événement de
        # sa réponse LinkCheckAns ; une DevStatusReq est toujours annotée. Un downlink perdu
        # n'apporte ni réponse ni requête.
        if ok and job.fopts:
            cmds = lsim_mac.decode_all(job.fopts, downlink=True)
            # Une seule réponse par descente, même si elle acquitte plusieurs requêtes.
            answers = [c for c in cmds if isinstance(c, (LinkCheckAns, DeviceTimeAns))]
            if answers and job.kind != "mac_answer":
                add(start, "mac_answer", d, [], "delivered")
            for cmd in cmds:
                if isinstance(cmd, DevStatusReq):
                    add(start, "mac_request", d, [], "DevStatusReq")

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    return tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=0,
                      hops=hops, outcome=outcome)
        for k, (t, _order, kind, d, hops, outcome) in enumerate(pending)
    )


def _plan(records: Sequence[TxRecord], radios: Sequence[DeviceRadio], options: ProtocolOptions,
          joined: dict[int, int], mac: Optional[MacSchedule] = None):
    """Une passe de planification : rôles, downlinks, émissions passerelle, jointures obtenues."""
    roles = _join_roles(records, joined, options)
    jobs = _downlink_jobs(records, radios, options, roles, mac)
    starts, fenetres, busy = _schedule_gateway(jobs, options)
    obtenues = _joined_times(jobs, starts, fenetres, records, radios, options)
    return roles, jobs, starts, busy, fenetres, obtenues


def build_protocol_events(records: Sequence[TxRecord], radios: Sequence[DeviceRadio],
                          options: ProtocolOptions,
                          mac: Optional[MacSchedule] = None) -> tuple[ProtocolEvent, ...]:
    """Événements dérivés d'une trace déjà produite (sans nouvelle itération du moteur).

    Les émissions passerelle sont celles des downlinks planifiés à partir de cette trace : seul
    l'état des jointures est itéré. Pour une trace cohérente avec le moteur, utiser `build_trace`.
    """
    joined: dict[int, int] = {}
    seen: dict[tuple, int] = {(): 0}
    for iteration in range(1, MAX_ITERATIONS_TRACE + 1):
        roles, jobs, starts, _busy, fenetres, new_joined = _plan(records, radios, options,
                                                                 joined, mac)
        if new_joined == joined:
            return _events(records, radios, jobs, starts, roles, mac, fenetres, options)
        signature = tuple(sorted(new_joined.items()))
        if signature in seen:
            raise RuntimeError(
                "pas de point fixe pour les jointures (build_protocol_events) : état répété à "
                f"l'identique (cycle de période {iteration - seen[signature]}) "
                f"après {iteration} itérations")
        seen[signature] = iteration
        joined = new_joined
    raise RuntimeError("pas de point fixe pour les jointures (build_protocol_events) "
                       f"après {MAX_ITERATIONS_TRACE} itérations")


def _schedule_of(scenario: Scenario) -> Optional[MacSchedule]:
    """Calendrier MAC du scénario ; None si le bloc `mac:` est absent ou désactivé."""
    m = scenario.model.mac
    if m is None or (m.link_check_every == 0 and m.device_status_every == 0
                     and m.device_time_every == 0):
        return None
    return MacSchedule(link_check_every=m.link_check_every,
                       device_status_every=m.device_status_every,
                       link_margin_installation_db=m.link_margin_installation_db,
                       device_time_every=m.device_time_every)


def mac_reservations(scenario: Scenario, devices) -> tuple[tuple[int, int, int], ...]:
    """Calendrier des octets MAC réservés : triplets (index de dispositif, rang, octets).

    Calculé avant la simulation, à partir du scénario seul : même scénario, mêmes réservations. Les
    réservations sont conservatrices (voir `lsim.mac_plan`).
    """
    schedule = _schedule_of(scenario)
    if schedule is None:
        return ()
    out = []
    for i, d in enumerate(devices):
        for rank, extra in mac_plan.reservations(schedule, d.messages):
            out.append((i, rank, extra))
    return tuple(out)


def _native_plan_applies(options: ProtocolOptions, mac: Optional[MacSchedule]) -> bool:
    """Planification des descentes en natif (S0) : passerelle unique, sans jointure ni commande MAC.

    Ces cas sont couverts par la parité avec la version Python (`tests/test_downlink_plan_parity.py`).
    Les autres restent sur la version Python.
    """
    return not options.join and mac is None


def _build_trace_native(devices, radios, gateway, propagation, environment,
                        options: ProtocolOptions) -> TraceRun:
    """Trace causale (S1) : une seule exécution, descentes planifiées à la fin de chaque trame.

    Pas de point fixe : l'occupation passerelle utilisée par le moteur est celle que produit le
    planificateur natif sur la trace obtenue (contrôle d'égalité, sans itération).

    Repli RX2 (I3) : les **deux** producteurs reçoivent la même table. Avant I3, seul le
    planificateur par lot pouvait en recevoir une — aucune entrée causale ne l'acceptait — si
    bien que le repli dès qu'il se produisait faisait diverger les deux. La passer aux deux est
    la condition pour que le contrôle d'égalité ci-dessous reste vérifié.
    """
    from lsim.downlink_plan import DeviceRx2, plan_native, plan_native_v2, simulate_causal
    from lsim.simulator import effective_frontends
    device_rf, gateway_rf = effective_frontends(devices, gateway)
    table = _table_rx2(radios) if options.rx2_fallback else None
    result, busy = simulate_causal(devices, gateway, propagation, environment, radios, options,
                                   device_rf=device_rf, gateway_rf=gateway_rf, rx2=table)
    events, plan_busy = ((plan_native_v2(result.records, radios, options, table)
                          if table is not None
                          else plan_native(result.records, radios, options)))
    if tuple(plan_busy) != tuple(busy):
        raise RuntimeError("occupation passerelle incohérente entre le moteur et le planificateur")
    if len(events) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(events)} ; limite {MAX_EVENTS})")
    return TraceRun(per_device=result.per_device, totals=result.totals,
                    gateway=result.gateway, records=result.records, events=events,
                    gateway_tx=tuple(busy))


def _downlink_duty_cycle(scenario, gateway, options, active: bool = True):
    """Règle de rapport cyclique **descendant** du scénario, ou `None` si elle n'est pas définie.

    Trois conditions, toutes nécessaires :

    - une région **unique** est déclarée par les groupes : sans elle, la sous-bande de la
      descente est indéfinie, et aucune contrainte n'est appliquée ;
    - cette région définit des sous-bandes (US915 et AU915 n'en ont pas : rien à appliquer) ;
    - `enforce_duty_cycle` est vrai.

    Une région absente ou plusieurs régions différentes ne sont **pas** une erreur : c'est
    l'absence d'une information que le scénario ne porte pas. La contrainte est alors
    inertie, et non pas devinée.
    """
    if not active:
        return None
    from lsim.arbitre import DownlinkDutyCycle
    from lsim.power import gateway_tx
    from lsim.regions import PROFILES

    regions = {groupe.region for groupe in scenario.model.groups if groupe.region}
    if len(regions) != 1:
        return None
    profile = PROFILES.get(regions.pop())
    if profile is None or not profile.sub_bands:
        return None
    return DownlinkDutyCycle(profile, gateway_tx(gateway, options.gateway_tx_power_dbm),
                             enabled=True)


def _build_trace_retransmissions(scenario, devices, radios, gateway, propagation, environment,
                                 options: ProtocolOptions) -> TraceRun:
    """Trace d'un scénario à retransmissions : une entrée par transmission, indices physiques.

    Le module `retransmissions` raisonne sur des terminaux virtuels (un par transmission) ; cette
    fonction les ramène aux terminaux du scénario, seuls connus de l'appelant et de l'export.
    """
    from dataclasses import replace as _remplacer

    from lsim.join import BLOCKED_DUTY_CYCLE  # import local : `lsim.join` importe `lsim.ack_mac`
    from lsim.retransmissions import simulate_confirmed_uplinks

    etat = scenario.model.retransmissions
    devoir = _downlink_duty_cycle(scenario, gateway, options, active=etat.enforce_duty_cycle)
    resultat = simulate_confirmed_uplinks(
        devices, gateway, propagation, radios, options, etat.options(),
        energy_profile=etat.energy_profile, environment=environment, with_engine_output=True,
        device_classes=scenario.device_classes(), duty_cycle=devoir)
    moteur, evenements = resultat.trace, resultat.events
    if moteur is None:
        raise RuntimeError("moteur sans sortie : trace de réémission impossible")
    plan = resultat.attempts

    records = tuple(
        TxRecord(plan[r.device_index].device if r.device_index < len(plan) else r.device_index,
                 r.start_ns, r.end_ns, r.spreading_factor, r.rssi_dbm, r.outcome)
        for r in moteur.records)

    # Compteurs par terminal physique : somme des transmissions qui lui appartiennent.
    sent = [0] * len(devices)
    recu = [0] * len(devices)
    perdu_sens = [0] * len(devices)
    perdu_coll = [0] * len(devices)
    perdu_busy = [0] * len(devices)
    airtime = [0] * len(devices)
    for index, compteurs in enumerate(moteur.per_device):
        physique = plan[index].device if index < len(plan) else index
        sent[physique] += compteurs.sent
        recu[physique] += compteurs.received
        perdu_sens[physique] += compteurs.lost_sensitivity
        perdu_coll[physique] += compteurs.lost_collision
        perdu_busy[physique] += compteurs.lost_gateway_busy
        airtime[physique] += compteurs.airtime_ns

    per_device = tuple(
        Counters(sent[i], recu[i], perdu_sens[i], perdu_coll[i], airtime[i], perdu_busy[i])
        for i in range(len(devices)))
    totaux = moteur.totals

    # Événements : indices virtuels ramenés aux terminaux, hops renommés en conséquence.
    remappes = []
    for evenement in evenements:
        index = evenement.device_index
        physique = plan[index].device if index < len(plan) else index
        hops = tuple(
            _remplacer(hop, from_id=hop.from_id.replace(f"dev:{index}", f"dev:{physique}"),
                       to_id=hop.to_id.replace(f"dev:{index}", f"dev:{physique}"))
            for hop in evenement.hops)
        remappes.append(_remplacer(evenement, device_index=physique, hops=hops))
    # Jointures radio : chaque tentative est un evenement, avec l'issue que le moteur a rendue.
    # Le Join-Accept n'apparait que si le Join-Request a ete recu (sinon rien n'a ete emis).
    for tentative in getattr(resultat, "joins", ()):
        radio = radios[tentative.device]
        # Un Join-Request refusé par le rapport cyclique n'est **pas** une émission : il apparaît
        # en trace, mais avec l'issue `suppressed` du contrat (rien n'a été transmis), jamais
        # comme une transmission réussie.
        issue_requete = ("suppressed" if tentative.request_outcome == BLOCKED_DUTY_CYCLE
                         else tentative.request_outcome)
        remappes.append(ProtocolEvent(
            0, tentative.request_ns, "join_request", tentative.device, 0,
            (HopEvent(_dev(tentative.device), "gw:0", tentative.request_ns, radio.freq_hz,
                      radio.dr, None, issue_requete),), issue_requete))
        # Une émission par Join-Accept réellement transmis : RX1, puis RX2 en secours, puis rejeux.
        # Le rejeu reçu est « suppressed » au contrat : le terminal le décode et le refuse.
        #
        # Fréquence de la fenêtre **réellement émise** : RX1 et RX2 ne sont pas dans la même
        # sous-bande, et l'imputation du rapport cyclique descendant en dépend. La fenêtre est lue
        # sur l'émission (`emission.window`), jamais déduite de la fréquence : plusieurs profils
        # régionaux (US915, AS923, AU915 [H]) donnent à RX1 et RX2 la même fréquence, donc la
        # fréquence ne permet pas de remonter à la fenêtre.
        #
        # Un rejeu porte `window == "replay"` : la fenêtre dont la PHY l'a servi est dans
        # `fenetre_source`, renseignée par le module `join`. On la lit, on ne la reconstruit pas :
        # l'inférence par « dernière acceptation vue » dépendait de l'ordre de la liste.
        for emission in tentative.accepts:
            issue = "suppressed" if emission.outcome == "replayed" else emission.outcome
            fenetre_source = getattr(emission, "fenetre_source", None)
            if fenetre_source not in ("rx1", "rx2"):
                fenetre_source = emission.window if emission.window in ("rx1", "rx2") else "rx1"
            freq_hz = radio.rx2_hz if fenetre_source == "rx2" else radio.rx1_hz
            remappes.append(ProtocolEvent(
                0, emission.at_ns, "join_accept", tentative.device, 0,
                (HopEvent("gw:0", _dev(tentative.device), emission.at_ns, freq_hz,
                          None, None, issue),), issue))

    # Jointures declarees (sans radio) : elles ouvrent une session, donc remettent les compteurs a
    # zero. Le Join-Request precede le Join-Accept de JOIN_ACCEPT_DELAY1 (5 s), borne a l'origine.
    for t_s in etat.session_joins_s:
        instant_accept = t_s * 1_000_000_000
        instant_demande = max(0, instant_accept - JOIN_ACCEPT_DELAY1_NS)
        for appareil in range(len(devices)):
            radio = radios[appareil]
            remappes.append(ProtocolEvent(
                0, instant_demande, "join_request", appareil, 0,
                (HopEvent(_dev(appareil), "gw:0", instant_demande, radio.freq_hz, radio.dr,
                          None, "delivered"),), "delivered"))
            remappes.append(ProtocolEvent(
                0, instant_accept, "join_accept", appareil, 0,
                (HopEvent("gw:0", _dev(appareil), instant_accept, radio.rx1_hz, None, None,
                          "delivered"),), "delivered"))

    remappes.sort(key=lambda e: e.t_ns)
    evenements_finaux = tuple(_remplacer(e, seq=k) for k, e in enumerate(remappes))

    return TraceRun(per_device=per_device, totals=totaux, gateway=moteur.gateway,
                    records=records, events=evenements_finaux,
                    gateway_tx=tuple(resultat.gateway_tx), retransmissions=resultat)


def build_trace(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> TraceRun:
    """Déploie le scénario et calcule la trace cohérente avec les émissions de la passerelle.

    Point fixe : les trames montantes dépendent des émissions passerelle, qui dépendent des
    uplinks reçus. L'itération s'arrête quand les émissions utilisées par le moteur sont celles
    que produit la trace obtenue. Une répétition exacte de l'état est un cycle : erreur explicite
    immédiate. Pas de convergence après `MAX_ITERATIONS_TRACE` itérations : erreur explicite aussi.
    Aucun résultat approximatif n'est renvoyé.
    """
    devices, group_of, _indices = scenario.deploy()
    if sum(d.messages for d in devices) > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    radios = device_radios(scenario)
    gateway, propagation, environment = scenario.gateway(), scenario.propagation(), scenario.environment
    etat = scenario.model.retransmissions
    if etat is not None and etat.is_active:
        # Uplinks confirmés avec réémissions : chemin dédié, voir `_build_trace_retransmissions`.
        return _build_trace_retransmissions(scenario, devices, radios, gateway, propagation,
                                            environment, options)
    from lsim.mac_loop import closed_loop_applies  # import local : évite un cycle
    if closed_loop_applies(scenario):
        # LinkADR / DutyCycle : une seule exécution native, descentes créées par le moteur.
        return _build_trace_closed_loop(scenario, devices, group_of, radios, gateway, propagation,
                                        environment, options)
    mac = _schedule_of(scenario)
    reservations = mac_reservations(scenario, devices)

    if _native_plan_applies(options, mac):
        return _build_trace_native(devices, radios, gateway, propagation, environment, options)

    return _build_trace_python(devices, radios, gateway, propagation, environment, reservations,
                               options, mac)


def build_trace_closed_loop(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> TraceRun:
    """Trace produite par la boucle fermée, même sans LinkADR ni DutyCycle.

    Sert à vérifier la parité avec le chemin historique (`build_trace`) sur les réservations MAC.
    `build_trace` n'emprunte ce chemin que si `closed_loop_applies` est vrai.
    """
    devices, group_of, _indices = scenario.deploy()
    if sum(d.messages for d in devices) > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    return _build_trace_closed_loop(scenario, devices, group_of, device_radios(scenario),
                                    scenario.gateway(), scenario.propagation(),
                                    scenario.environment, options)


def _build_trace_closed_loop(scenario, devices, group_of, radios, gateway, propagation, environment,
                             options: ProtocolOptions) -> TraceRun:
    """Boucle fermée S2/S3 : une exécution, uplinks, réservations MAC et descentes du moteur natif."""
    from lsim.closed_loop import OUTCOME_CODES
    from lsim.closed_loop_v3 import simulate_closed_loop_v3
    from lsim.mac_loop import (
        check_closed_loop, loop_options, loop_regions, mac_byte_accounting, mac_slots,
    )
    check_closed_loop(scenario, options)
    schedule = _schedule_of(scenario)
    regions = loop_regions(scenario, group_of)
    # ABI v3, et non v2 : c'est la seule qui rapporte les canaux laissés au terminal
    # (`terminals`), que la v2 ne porte pas. L'équivalence sur les champs communs a été
    # mesurée avant la bascule — comptages, uplinks, descendantes, occupations et file MAC
    # identiques sur six scénarios — sinon ce ne serait pas une migration mais une
    # régression silencieuse de toutes les mesures existantes.
    out = simulate_closed_loop_v3(devices, gateway, propagation, radios,
                                  regions, loop_options(scenario, options),
                                  mac=mac_slots(schedule, devices),
                                  environment=environment)
    records = tuple(
        TxRecord(u.device, u.start_ns, u.end_ns, u.spreading_factor, u.rssi_dbm,
                 OUTCOME_CODES[u.outcome])
        for u in out.uplinks)
    # Canaux laissés au terminal par le serveur. Ils ne sont lisibles que sur la v3 : l'ABI
    # v2 ne les porte pas, et c'est la raison d'être de la bascule. `terminals` est vide
    # quand le moteur n'a rien à en dire — le champ reste alors absent plutôt que de
    # publier une liste vide qui ferait croire à une observation.
    canaux = {t.device: TerminalChannels(
        dr_masks={ch: mask for ch, mask in sorted(t.dr_masks.items())},
        enabled=tuple(t.enabled)) for t in (out.terminals or ())}
    # Puissance appliquée, un relevé par dispositif. `u.power_index` existe sur chaque
    # uplink de la boucle fermée : il était simplement jeté à la ligne ci-dessus, si bien
    # que l'atelier montrait le débit commandé par le serveur sans jamais dire qu'il avait
    # aussi baissé la puissance — le versant « autonomie » de la même décision.
    # Le pas est lu par dispositif : un plan par passerelle, et non une moyenne qui
    # donnerait une réduction en décibels n'appartenant à aucun des deux.
    puissances: dict[int, DevicePower] = {}
    for u in out.uplinks:
        connue = puissances.get(u.device)
        pas_db = regions[u.device].power_step_tenth_db / 10.0 if u.device < len(regions) else None
        if pas_db is None:
            continue
        puissances[u.device] = DevicePower(
            first_index=connue.first_index if connue is not None else u.power_index,
            last_index=u.power_index, step_db=pas_db)
    events = _closed_loop_events(out, radios, options, schedule)
    return TraceRun(per_device=out.per_device, totals=out.totals, gateway=out.load, records=records,
                    events=events, gateway_tx=out.busy, mac_queue=out.mac_queue,
                    mac_bytes=mac_byte_accounting(schedule, devices, out.uplinks),
                    device_power=puissances or None,
                    device_channels=canaux or None)


def _closed_loop_events(out, radios: Sequence[DeviceRadio], options: ProtocolOptions,
                        mac: Optional[MacSchedule] = None) -> tuple[ProtocolEvent, ...]:
    """Événements de la boucle fermée, au même format et au même ordre que `_events`.

    Pour chaque uplink : l'uplink, ses requêtes du calendrier, la réponse DevStatusAns s'il y a
    lieu, puis la descente qui lui répond (le moteur en crée au plus une par uplink reçu).
    """
    from lsim.closed_loop import (
        ANSWER_DEVICE_STATUS, CMD_DEVICE_STATUS, CMD_DEVICE_TIME, CMD_DUTY_CYCLE, CMD_LINK_ADR,
        CMD_LINK_CHECK, OUTCOME_CODES,
    )
    pending: list[tuple[int, int, str, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, tuple(hops), outcome))

    down_of = {dl.uplink: dl for dl in out.downlinks}
    rank_of: dict[int, int] = defaultdict(int)
    for a, u in enumerate(out.uplinks):
        rank_of[u.device] += 1
        code = OUTCOME_CODES[u.outcome]
        radio = radios[u.device]
        hops = [HopEvent(_dev(u.device), "gw:0", u.start_ns, radio.freq_hz, radio.dr, u.rssi_dbm,
                         _HOP_OUTCOME[code])]
        received = code == TxRecord.OUTCOME_RECEIVED
        if received:
            hops.append(HopEvent("gw:0", "ns", u.end_ns, radio.freq_hz, radio.dr, None, "delivered"))
        add(u.start_ns, "uplink", u.device, hops, _UPLINK_OUTCOME[code])
        if mac is not None:
            for cmd in uplink_requests(mac, rank_of[u.device]):
                add(u.start_ns, "mac_request", u.device, [], _MAC_NAME[type(cmd)])
        if received:
            # Réponses portées par cet uplink : confirmées parce qu'il est reçu.
            if u.answer_mask & 1:
                add(u.start_ns, "mac_answer", u.device, [], "LinkADRAns")
            if u.answer_mask & 2:
                add(u.start_ns, "mac_answer", u.device, [], "DutyCycleAns")
            if u.answer_mask & ANSWER_DEVICE_STATUS:
                add(u.start_ns, "mac_answer", u.device, [], "DevStatusAns")

        dl = down_of.get(a)
        if dl is None:
            continue
        radio = radios[dl.device]
        dev = _dev(dl.device)
        if dl.start_ns is None:
            hop = HopEvent("gw:0", dev, dl.t_open_ns, radio.rx1_hz, None, None, "not_listened")
            add(dl.t_open_ns, "rx_window_missed", dl.device, [hop], "gateway_busy")
            continue
        if dl.device_missed:
            hop = HopEvent("gw:0", dev, dl.start_ns, radio.rx1_hz, None, None, "not_listened")
            add(dl.t_open_ns, "rx_window_missed", dl.device, [hop], "device_transmitting")
            continue
        ok = dl.delivered
        down_hop = HopEvent("gw:0", dev, dl.start_ns, radio.rx1_hz, None, None,
                            "delivered" if ok else "lost_sensitivity")
        answers = bool(dl.commands & (CMD_LINK_CHECK | CMD_DEVICE_TIME))
        if dl.kind == "ack":
            kind, content = "ack", "ack_only"
        elif dl.kind == "data":
            kind = "downlink"
            content = "data_ack" if options.confirmed_uplinks else "data"
        elif answers:
            kind, content = "mac_answer", "delivered"  # downlink MAC seul portant une réponse
        else:
            kind, content = "downlink", "delivered"  # downlink MAC seul
        add(dl.start_ns, kind, dl.device, [down_hop], content if ok else "lost_sensitivity")
        if ok:
            # Une réponse par descente, même si elle acquitte plusieurs requêtes (comme `_events`).
            if answers and kind != "mac_answer":
                add(dl.start_ns, "mac_answer", dl.device, [], "delivered")
            if dl.commands & CMD_LINK_ADR:
                add(dl.start_ns, "mac_request", dl.device, [], "LinkADRReq")
            if dl.commands & CMD_DUTY_CYCLE:
                add(dl.start_ns, "mac_request", dl.device, [], "DutyCycleReq")
            if dl.commands & CMD_DEVICE_STATUS:
                add(dl.start_ns, "mac_request", dl.device, [], "DevStatusReq")

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    return tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=0, hops=hops,
                      outcome=outcome)
        for k, (t, _order, kind, d, hops, outcome) in enumerate(pending))


def _build_trace_python(devices, radios, gateway, propagation, environment, reservations,
                        options: ProtocolOptions, mac: Optional[MacSchedule]) -> TraceRun:
    """Point fixe Python (oracle, et chemin avec jointure ou MAC) : voir `build_trace`."""
    # La comparaison des occupations passe par une forme canonique, comme dans
    # `retransmissions` : deux occupations sont égales dès qu'elles couvrent les mêmes
    # intervalles, sans égard à l'ordre ni à d'éventuelles répétitions. La comparaison brute
    # (`new_busy == busy`) n'était correcte que parce que `GatewayArbiter.occupation` se
    # trouve être triée chronologiquement : une propriété d'implémentation, non une garantie.
    from lsim.retransmissions import _canonique

    busy: list[tuple[int, int]] = []
    joined: dict[int, int] = {}
    seen: dict[tuple, int] = {((), ()): 0}
    for iteration in range(1, MAX_ITERATIONS_TRACE + 1):
        result = simulate_uplinks_trace(devices, gateway, propagation, environment,
                                        gateway_busy=busy, reservations=reservations)
        roles, jobs, starts, new_busy, fenetres, new_joined = _plan(result.records, radios,
                                                                    options, joined, mac)
        if _canonique(new_busy) == _canonique(busy) and new_joined == joined:
            events = _events(result.records, radios, jobs, starts, roles, mac, fenetres,
                             options)
            return TraceRun(
                per_device=result.per_device,
                totals=result.totals,
                gateway=result.gateway,
                records=result.records,
                events=events,
                gateway_tx=tuple(busy),
            )
        signature = (_canonique(new_busy), tuple(sorted(new_joined.items())))
        if signature in seen:
            raise RuntimeError(
                "pas de point fixe entre trames montantes et émissions passerelle : état répété "
                f"à l'identique (cycle de période {iteration - seen[signature]}) "
                f"après {iteration} itérations")
        seen[signature] = iteration
        busy, joined = new_busy, new_joined
    raise RuntimeError(
        f"pas de point fixe entre trames montantes et émissions passerelle "
        f"après {MAX_ITERATIONS_TRACE} itérations")


# --- Passerelles multiples -------------------------------------------------------------------

_MULTI_UPLINK_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "received",
                         3: "lost_gateway_busy"}
# Saut mesh (journal natif) -> issue de l'événement `mesh_hop`.
_MESH_HOP_OUTCOME = {"received": "delivered", "lost_collision": "lost_collision",
                     "lost_half_duplex": "lost_half_duplex", "suppressed": "suppressed"}
MESH_BAND_HZ = 2_400_000_000
_MULTI_HOP_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "delivered", 3: "not_listened"}
_MULTI_DOWNLINK_OUTCOME = {0: "delivered", 1: "lost_sensitivity", 2: "gateway_busy",
                           3: "device_transmitting"}


# Retour mesh : bornes de la boucle à point fixe (ordonnancement des descentes ↔ trace).
MAX_MESH_RETURN_ITERATIONS = 64
# Une trame mesh (enveloppe comprise) fait 255 o au plus (`lsim.mesh.forward_frames`).
MAX_MESH_UPLINK_PAYLOAD_BYTES = 255 - MESH_ENVELOPE_UP_BYTES - DATA_FRAME_OVERHEAD_BYTES  # 228
MAX_MESH_DOWNLINK_PAYLOAD_BYTES = 255 - MESH_ENVELOPE_DOWN_BYTES - DATA_FRAME_OVERHEAD_BYTES  # 227


def mesh_payload_problem(scenario: Scenario, options: ProtocolOptions) -> Optional[tuple[str, str]]:
    """(champ, message) si une charge ne tient pas dans une trame mesh, sinon None.

    Refus anticipé : sans cela, la passe mesh échoue à l'exécution. Montant : seulement si un
    relais achemine (taille « device »). Descente : charge des downlinks de données.
    """
    cfg = scenario.model.mesh
    if cfg is None:
        return None
    if options.downlink_every > 0 and options.downlink_payload_bytes > MAX_MESH_DOWNLINK_PAYLOAD_BYTES:
        return ("protocol.downlink_payload_bytes",
                f"charge de descente de {options.downlink_payload_bytes} o : une trame mesh "
                f"est bornée à 255 o, enveloppe de {MESH_ENVELOPE_DOWN_BYTES} o et en-tête "
                f"comprises (maximum {MAX_MESH_DOWNLINK_PAYLOAD_BYTES} o sur mesh)")
    relays = any(g.mesh and g.name != cfg.border for g in scenario.gateway_models())
    if relays and cfg.frame_size == "device":
        biggest = max((g.payload_bytes for g in scenario.model.groups), default=0)
        if biggest > MAX_MESH_UPLINK_PAYLOAD_BYTES:
            return ("scenario",
                    f"charge montante de {biggest} o : une trame relayée est bornée à 255 o, "
                    f"enveloppe de {MESH_ENVELOPE_UP_BYTES} o comprise (maximum "
                    f"{MAX_MESH_UPLINK_PAYLOAD_BYTES} o sur mesh)")
    return None
# Départ au plus tôt d'une descente qui n'est pas acheminée (sentinelle natif : jamais).
MESH_NEVER_NS = (1 << 63) - 1


@dataclass(frozen=True)
class MeshLoad:
    """Charge mesh d'une passerelle relais : ses émissions (uplink et descente) sur la bande 2,4 GHz.

    `transmissions` : sauts émis ; `busy_ns` : somme de leur durée ; `lost_collision` et
    `lost_half_duplex` : ses émissions perdues à la réception ; `suppressed` : copies abandonnées
    (doublon déjà relayé). Les passes uplink et descente ne partagent pas le temps d'antenne.
    """

    transmissions: int = 0
    busy_ns: int = 0
    lost_collision: int = 0
    lost_half_duplex: int = 0
    suppressed: int = 0


@dataclass(frozen=True)
class MultiTraceRun:
    """Trace multi-passerelles : totaux et charges issus du même calcul natif que les événements.

    Mesh : `totals.received` et `per_device[i].received` sont les trames remises au LNS (après
    relais) ; `lost_mesh` (et `lost_mesh_by_device`) compte les trames décodées puis perdues sur le
    mesh. Hors mesh : `lost_mesh`, `lost_mesh_by_device` et `mesh_loads` valent None. Avec mesh,
    `mesh_loads` vaut None pour chaque passerelle sans mesh.
    """

    per_device: tuple[Counters, ...]
    totals: Counters
    per_gateway: tuple  # GatewayRxCounters, dans l'ordre de `gateway_names`
    gateway_names: tuple[str, ...]
    events: tuple[ProtocolEvent, ...]
    lost_mesh: Optional[int] = None
    lost_mesh_by_device: Optional[tuple[int, ...]] = None
    mesh_loads: Optional[tuple[Optional[MeshLoad], ...]] = None  # `gateway_names` ; None sans mesh
    # Réceptions par couple (dispositif, passerelle) : `rx_matrix[d][g]` trames décodées par la
    # passerelle `g` pour le dispositif `d`. C'est la seule grandeur qui dise « qui a entendu
    # qui » : l'événement servi ne porte que `gateway_index`, c'est-à-dire la **meilleure**
    # passerelle, et tracer depuis là dessinerait un trait là où trois passerelles ont décodé.
    rx_matrix: Optional[tuple[tuple[int, ...], ...]] = None


def _finite_or_none(x: float) -> Optional[float]:
    return float(x) if x == x and abs(x) != float("inf") else None


def _message_index(devices, trace) -> tuple[list[int], dict[tuple[int, int], int]]:
    """Indice d'émission (ordre du moteur : dispositifs dans l'ordre, puis k) de chaque
    enregistrement de trace, et index (dispositif, fin) -> enregistrement."""
    offsets, acc = [], 0
    for d in devices:
        offsets.append(acc)
        acc += d.messages
    if len(trace) != acc:
        raise RuntimeError("trace : nombre d'émissions incohérent")
    rank = [0] * len(devices)
    msg_of = [0] * len(trace)
    rec_by_end: dict[tuple[int, int], int] = {}
    for i in sorted(range(len(trace)), key=lambda i: (trace[i].device_index, trace[i].start_ns)):
        d = trace[i].device_index
        msg_of[i] = offsets[d] + rank[d]
        rank[d] += 1
        rec_by_end[(d, trace[i].end_ns)] = i
    return msg_of, rec_by_end


@dataclass(frozen=True)
class _MeshReturn:
    ready: list                # départ au plus tôt par émission (natif : -1 ou instant ; NEVER)
    status: dict               # descente (indice) -> "mesh" | "lost_mesh" | "uplink_lost"
    arrival: dict              # descente (indice) -> arrivée au relais (si "mesh")
    t_border: dict             # descente (indice) -> départ à la frontière
    routes: dict               # descente (indice) -> MeshDownlinkRoute


def _downlink_phy_bytes(dl, options: ProtocolOptions) -> int:
    if dl.join:
        return JOIN_ACCEPT_BYTES
    if dl.data:
        return DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes
    return ACK_FRAME_BYTES


def _downlink_requests(scenario: Scenario, models, options: ProtocolOptions, result,
                       delay_in: dict, msg_of: list[int], rec_by_end: dict):
    """Descentes à acheminer sur le mesh : une par descente vers un relais.

    `delay_in` : pour chaque émission (message) remise au LNS, délai de sa copie utile jusqu'à la
    frontière. Une descente dont l'uplink n'y figure pas n'est pas émise (`uplink_lost`).
    """
    border = scenario.model.mesh.border
    relays = {g.name for g in models if g.mesh and g.name != border}
    names = [g.name for g in models]
    requests = []
    pre_status: dict = {}
    msg_dl: dict = {}
    for j, dl in enumerate(result.downlinks):
        name = names[dl.gateway_index]
        if name not in relays:
            continue
        delay = JOIN_ACCEPT_DELAY1_NS if dl.join else RECEIVE_DELAY1_NS
        i = rec_by_end.get((dl.device_index, dl.t_open_ns - delay))
        if i is None:
            raise RuntimeError("retour mesh : émission d'origine introuvable")
        m = msg_of[i]
        msg_dl[j] = m
        if m not in delay_in:
            pre_status[j] = "uplink_lost"
            continue
        requests.append((j, name, result.trace[i].end_ns + delay_in[m],
                         _downlink_phy_bytes(dl, options)))
    return requests, pre_status, msg_dl


def _mesh_return(result, mesh, requests, pre_status: dict, msg_dl: dict,
                 n_messages: int) -> _MeshReturn:
    """Départs au plus tôt des descentes à partir de la passe mesh jointe."""
    ready = [-1] * n_messages
    status: dict = {}
    arrival: dict = {}
    t_border: dict = {}
    for j in pre_status:
        status[j] = pre_status[j]
        ready[msg_dl[j]] = MESH_NEVER_NS
    for j, _name, t0, _phy in requests:
        route = mesh.downlinks[j]
        t_border[j] = t0
        if route.delivered:
            status[j] = "mesh"
            arrival[j] = route.arrival_ns
            ready[msg_dl[j]] = route.arrival_ns
        else:
            status[j] = "lost_mesh"
            ready[msg_dl[j]] = MESH_NEVER_NS
    return _MeshReturn(ready=ready, status=status, arrival=arrival, t_border=t_border,
                       routes=dict(mesh.downlinks))


def _mesh_loads(models, mesh) -> tuple[Optional[MeshLoad], ...]:
    """Charge mesh par passerelle (émetteur = passerelle) : sauts montants et descendants, tous
    dans la passe jointe. None pour une passerelle sans mesh."""
    counts = {g.name: [0, 0, 0, 0, 0] for g in models if g.mesh}  # tx, busy, coll, hd, suppr
    for h in mesh.mesh_result.hops:
        c = counts[h.sender_id]
        if h.outcome == "suppressed":
            c[4] += 1
            continue
        c[0] += 1
        c[1] += h.t_end_ns - h.t_start_ns
        if h.outcome == "lost_collision":
            c[2] += 1
        elif h.outcome == "lost_half_duplex":
            c[3] += 1
    return tuple(MeshLoad(*counts[g.name]) if g.mesh else None for g in models)


def _direct_deliverer(decoded_mask: int, models, border: str) -> Optional[int]:
    """Index de la passerelle qui remet directement une trame décodée (None si aucune)."""
    decoders = [g for g in range(len(models)) if (decoded_mask >> g) & 1]
    for g in decoders:
        if models[g].name == border:
            return g
    for g in decoders:
        if not models[g].mesh:
            return g
    return None


def _rx_matrix(trace, n_devices: int, n_gateways: int) -> Optional[tuple[tuple[int, ...], ...]]:
    """Réceptions par couple (dispositif, passerelle), depuis le masque de décodage.

    Une seule passe sur la trace : la construire par couple coûterait `dispositifs × passerelles`
    parcours, ce qui se paie sur les gros scénarios.

    Le masque dit « a décodé », pas « a entendu » : c'est la granularité à laquelle une liaison
    radio est significative. Une trame reçue par trois passerelles compte trois fois — une fois
    par liaison, et non une fois pour la trame.
    """
    if not trace or n_devices <= 0 or n_gateways <= 0:
        return None
    matrice = [[0] * n_gateways for _ in range(n_devices)]
    for r in trace:
        masque = r.decoded_mask
        if not masque:
            continue
        ligne = matrice[r.device_index]
        g = 0
        while masque:
            if masque & 1:
                ligne[g] += 1
            masque >>= 1
            g += 1
    return tuple(tuple(l) for l in matrice)


def build_multi_trace(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> MultiTraceRun:
    """Trace des passerelles multiples (déduplication serveur, downlinks par la meilleure passerelle).

    Join (`options.join`) : une trame montante est une join-request tant que le dispositif n'est pas
    jointé ; la join-request décodée reçoit un join-accept à fin + 5 s par la meilleure passerelle, et
    le dispositif est jointé si ce join-accept lui parvient. Une join-request perdue est répétée à
    l'émission suivante. Ce n'est pas la règle du mono (première émission seulement) : voir docs.

    Mesh (`scenario.model.mesh`) : la passe mesh (`mesh_pass`, la même que `run_scenario`) relaie
    chaque copie vers la frontière. Un événement `mesh_hop` par émission mesh (ou copie supprimée),
    à l'instant d'émission. Une trame décodée mais non remise est une perte `lost_mesh`.
    Descentes vers un relais : acheminées depuis la frontière sur le mesh (un événement
    `mesh_downlink_hop` par saut descendant) ; elles partent au plus tôt à leur arrivée au relais.
    Perdue sur le mesh : outcome `lost_mesh`. Arrivée après la fenêtre RX1 : `mesh_late`. Une
    descente d'un uplink non remis au LNS n'est pas émise. Ces descentes occupent la passerelle
    relais comme les autres. Boucle à point fixe (descentes ↔ trace), bornée par
    `MAX_MESH_RETURN_ITERATIONS`.

    Les totaux, les compteurs par dispositif et la charge par passerelle viennent du même appel natif
    (`simulate_multi_downlinks`) que les événements : ils concordent par construction.
    """
    problem = mesh_payload_problem(scenario, options)
    if problem is not None:
        raise ValueError(problem[1])
    devices, _group_of, _indices = scenario.deploy()
    if sum(d.messages for d in devices) > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    radios = device_radios(scenario)
    models = scenario.gateway_models()
    names = tuple(g.name for g in models)
    gateways = scenario.gateways()
    rule = DownlinkRule(ack_uplinks=options.confirmed_uplinks, every=options.downlink_every,
                        payload_bytes=options.downlink_payload_bytes,
                        gateway_tx_power_dbm=options.gateway_tx_power_dbm,
                        device_antenna_gain_dbi=options.device_antenna_gain_dbi,
                        device_rx_offset_db=options.device_rx_offset_db,
                        join=options.join, rx2_sf=_rx2_spreading_factor(scenario))
    # I5-a : ces radios étaient calculées plus haut mais ne franchissaient pas la frontière ; le
    # moteur retenait donc l'hypothèse « RX1 au SF montant, 125 kHz ». Une table rx2 impose en
    # retour `rule.rx2_sf == 0` (décision i5-a-2) : la fenêtre de repli est alors décrite par la
    # table, seule source, et non plus par un scalaire qui la doublerait.
    #
    # Sans plan régional, `dr` est None : RX1 vaut alors (SF montant, 125 kHz), la diagonale — la
    # table n'aurait aucun effet. On ne la passe pas, ce qui conserve la garantie d'I3 :
    # « aucun scénario historique ne change ».
    if any(r.dr is None for r in radios):
        radios_table, rx2 = None, None
    else:
        radios_table, rx2 = radios, _table_rx2(radios)
        if any(r.rx2_sf for r in rx2):
            rule = DownlinkRule(ack_uplinks=rule.ack_uplinks, every=rule.every,
                                payload_bytes=rule.payload_bytes,
                                gateway_tx_power_dbm=rule.gateway_tx_power_dbm,
                                device_antenna_gain_dbi=rule.device_antenna_gain_dbi,
                                device_rx_offset_db=rule.device_rx_offset_db,
                                join=rule.join, rx2_sf=0)
    mesh = None
    plan: Optional[_MeshReturn] = None
    if scenario.model.mesh is None:
        result = simulate_multi_downlinks(devices, gateways, scenario.propagation(), rule,
                                          scenario.environment, radios=radios_table, rx2=rx2)
    else:
        # Point fixe sur (départs au plus tôt des descentes, délai frontière de chaque uplink) :
        # la passe jointe (montant et descente partagent le temps d'antenne) dépend des descentes,
        # qui dépendent des arrivées à la frontière. Les émissions sont indexées par message,
        # stables d'une itération à l'autre (seul leur résultat change).
        total = sum(d.messages for d in devices)
        ready: list = [-1] * total
        delay_in: dict = {m: 0 for m in range(total)}  # hypothèse initiale : frontière directe
        for _ in range(MAX_MESH_RETURN_ITERATIONS):
            result = simulate_multi_downlinks(devices, gateways, scenario.propagation(), rule,
                                              scenario.environment, dl_ready_ns=ready,
                                              radios=radios_table, rx2=rx2)
            msg_of, rec_by_end = _message_index(devices, result.trace)
            requests, pre_status, msg_dl = _downlink_requests(scenario, models, options, result,
                                                              delay_in, msg_of, rec_by_end)
            mesh = mesh_pass(scenario, devices, models, result.trace, with_hops=True,
                             downlinks=requests)
            decoded = {i for i, r in enumerate(result.trace) if r.outcome == 2}
            if not mesh.delivered_frames <= decoded:
                raise RuntimeError("mesh : trame remise sans avoir été décodée (incohérent)")
            plan = _mesh_return(result, mesh, requests, pre_status, msg_dl, total)
            delay_out = {msg_of[i]: mesh.border_delay_ns[i] for i in mesh.delivered_frames}
            if plan.ready == ready and delay_out == delay_in:
                break
            ready, delay_in = plan.ready, delay_out
        else:
            raise RuntimeError("retour mesh : pas de point fixe après "
                               f"{MAX_MESH_RETURN_ITERATIONS} itérations")
    delivered: frozenset = mesh.delivered_frames if mesh is not None else frozenset()
    pending: list[tuple[int, int, str, int, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, gw: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, gw, tuple(hops), outcome))

    for i_rec, r in enumerate(result.trace):
        d = r.device_index
        radio = radios[d]
        best = r.best_gateway
        to_id = f"gw:{names[best]}" if best >= 0 else "gw:none"
        hops = [HopEvent(_dev(d), to_id, r.start_ns, radio.freq_hz, radio.dr,
                         _finite_or_none(r.best_rssi_dbm), _MULTI_HOP_OUTCOME[r.outcome])]
        outcome = _MULTI_UPLINK_OUTCOME[r.outcome]
        if mesh is not None and r.outcome == 2:
            if i_rec in delivered and i_rec in mesh.via_mesh_frames:
                # Remise par la frontière, après le délai de la copie utile (saut mesh inclus).
                arrival = r.end_ns + mesh.border_delay_ns.get(i_rec, 0)
                hops.append(HopEvent(f"gw:{scenario.model.mesh.border}", "ns", arrival,
                                     radio.freq_hz, radio.dr, None, "delivered"))
            elif i_rec in delivered:
                # Remise directe : la passerelle qui remet est la frontière si elle a décodé,
                # sinon une passerelle à backhaul IP (le « meilleur » RSSI peut être un relais).
                deliverer = _direct_deliverer(r.decoded_mask, models, scenario.model.mesh.border)
                src = f"gw:{names[deliverer]}" if deliverer is not None else to_id
                hops.append(HopEvent(src, "ns", r.end_ns, radio.freq_hz, radio.dr, None, "delivered"))
            else:
                outcome = "lost_mesh"
        elif r.outcome == 2 and best >= 0:
            hops.append(HopEvent(to_id, "ns", r.end_ns, radio.freq_hz, radio.dr, None, "delivered"))
        kind = "join_request" if r.join_request else "uplink"
        add(r.start_ns, kind, d, max(best, 0), hops, outcome)

    if mesh is not None:
        idx_of = {name: k for k, name in enumerate(names)}
        for h in mesh.uplink_hops:
            d = result.trace[h.frame_id].device_index
            hop = HopEvent(f"gw:{h.sender_id}", f"gw:{h.receiver_id}", h.t_start_ns, MESH_BAND_HZ,
                           None, None, _MESH_HOP_OUTCOME[h.outcome])
            add(h.t_start_ns, "mesh_hop", d, idx_of[h.sender_id], [hop],
                _MESH_HOP_OUTCOME[h.outcome])
        for j, route in plan.routes.items():
            dl = result.downlinks[j]
            for h in route.hops:
                hop = HopEvent(f"gw:{h.sender_id}", f"gw:{h.receiver_id}", h.t_start_ns,
                               MESH_BAND_HZ, None, None, _MESH_HOP_OUTCOME[h.outcome])
                add(h.t_start_ns, "mesh_downlink_hop", dl.device_index, idx_of[h.sender_id],
                    [hop], _MESH_HOP_OUTCOME[h.outcome])

    for j, dl in enumerate(result.downlinks):
        d, g = dl.device_index, dl.gateway_index
        radio = radios[d]
        gw_id = f"gw:{names[g]}"
        if dl.join:
            kind = "join_accept"
        else:
            kind = "downlink" if dl.data else "ack"
        st = plan.status.get(j) if plan is not None else None
        if st == "uplink_lost":
            continue  # pas d'uplink au LNS : pas de descente
        if st == "lost_mesh":
            t0 = plan.t_border[j]
            hop = HopEvent("ns", gw_id, t0, radio.rx1_hz, None, None, "lost_mesh")
            add(t0, kind, d, g, [hop], "lost_mesh")
            continue
        # Arrivée après la fin de RX2 (RX1 et RX2 de 1 s chacune, à partir de t_open) : « tardive ».
        late = (st == "mesh" and dl.outcome == 2
                and plan.arrival[j] > dl.t_open_ns + 2 * RECEIVE_DELAY1_NS)
        if dl.outcome in (2, 3):
            hop = HopEvent(gw_id, _dev(d), dl.t_open_ns, radio.rx1_hz, None, None, "not_listened")
            outcome = "mesh_late" if late else _MULTI_DOWNLINK_OUTCOME[dl.outcome]
            add(dl.t_open_ns, "rx_window_missed", d, g, [hop], outcome)
            continue
        start = dl.start_ns
        ok = dl.outcome == 0
        hop = HopEvent(gw_id, _dev(d), start, radio.rx1_hz, None, None,
                       "delivered" if ok else "lost_sensitivity")
        if ok:
            if dl.join:
                outcome = "delivered"
            elif dl.data:
                # Même libellé que le mono : une charge sur uplink confirmé porte aussi l'ACK.
                outcome = "data_ack" if options.confirmed_uplinks else "data"
            else:
                outcome = "ack_only"
        else:
            outcome = "lost_sensitivity"
        if dl.join:
            # Même forme que le mono : le join-accept passe d'abord par le serveur (sans perte).
            hops = [HopEvent("ns", gw_id, start, radio.rx1_hz, None, None, "delivered"), hop]
        else:
            hops = [hop]
        add(start, kind, d, g, hops, outcome)

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    events = tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=g,
                      hops=hops, outcome=outcome)
        for k, (t, _order, kind, d, g, hops, outcome) in enumerate(pending)
    )
    net = result.network
    rx = _rx_matrix(result.trace, len(devices), len(names))
    if mesh is None:
        totals = Counters(net.sent, net.received, net.lost_sensitivity, net.lost_collision,
                          net.airtime_ns, net.lost_gateway_busy)
        return MultiTraceRun(per_device=result.per_device, totals=totals,
                             per_gateway=result.per_gateway, gateway_names=names, events=events,
                             rx_matrix=rx)
    # Mesh : remises au LNS par dispositif ; le reste des trames décodées est « lost_mesh ».
    per_device, lost_by_device = [], []
    for d, c in enumerate(result.per_device):
        got = mesh.delivered_by_device[d]
        if got > c.received:
            raise RuntimeError("mesh : plus de trames remises que de trames décodées")
        lost_by_device.append(c.received - got)
        per_device.append(Counters(c.sent, got, c.lost_sensitivity, c.lost_collision,
                                   c.airtime_ns, c.lost_gateway_busy))
    received = len(delivered)
    totals = Counters(net.sent, received, net.lost_sensitivity, net.lost_collision,
                      net.airtime_ns, net.lost_gateway_busy)
    return MultiTraceRun(per_device=tuple(per_device), totals=totals,
                         per_gateway=result.per_gateway, gateway_names=names, events=events,
                         lost_mesh=net.received - received,
                         lost_mesh_by_device=tuple(lost_by_device),
                         mesh_loads=_mesh_loads(models, mesh), rx_matrix=rx)


# Descentes reçues par le dispositif (ce qui consomme sa réception).
_DELIVERED_DOWNLINK_OUTCOMES = frozenset({"delivered", "data", "data_ack", "ack_only"})


def downlink_airtime_by_device(scenario: Scenario, events: Sequence[ProtocolEvent],
                               options: ProtocolOptions = ProtocolOptions()) -> tuple[int, ...]:
    """Airtime total (ns) des descendantes effectivement reçues, par dispositif.

    Dérivé des événements de la trace (même convention de longueur que les jobs de downlink) :
    join-accept, données (en-tête + `downlink_payload_bytes`), ACK seul. Les descendantes perdues
    (`lost_sensitivity`) et les fenêtres manquées ne consomment pas de réception.
    """
    radios = device_radios(scenario)
    total = [0] * len(radios)
    for ev in events:
        if ev.outcome not in _DELIVERED_DOWNLINK_OUTCOMES or ev.kind not in (
                "join_accept", "downlink", "ack"):
            continue
        if ev.kind == "join_accept":
            nbytes = JOIN_ACCEPT_BYTES
        elif ev.kind == "ack":
            nbytes = ACK_FRAME_BYTES
        else:
            nbytes = DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes
        total[ev.device_index] += _downlink_airtime_ns(radios[ev.device_index], nbytes)
    return tuple(total)

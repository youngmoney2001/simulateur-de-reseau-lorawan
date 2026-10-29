"""Trames de données (LoRaWAN 1.1) : vérification, compteurs, acquittements, file de downlinks.

Pour chaque uplink de données reçu d'une passerelle (une seule copie traitée, voir la limite
multi-passerelles) :

1. la session est retrouvée par DevAddr (inconnue : rejet) ;
2. le FCnt 16 bits du fil est reconstruit en 32 bits à partir du dernier compteur accepté :
   delta = (fcnt16 - dernier) mod 2^16. Delta 0 = retransmission de la dernière trame. Aucune
   limite d'écart n'est appliquée : LoRaWAN 1.0.4+ supprime MAX_FCNT_GAP (RP002-1.0.2 §2.3, note 10) ;
3. le MIC est vérifié avec le compteur reconstruit, TxDr et TxCh (B1 de l'uplink 1.1). Un canal
   non par défaut ou un débit hors plan EU868 rend le MIC impossible à vérifier : rejet ;
4. si la trame est acceptée, dans la même transaction SQLite : compteur montant persisté,
   confirmation de downlink en attente considérée close, downlink de la file émis en RX1 ;
5. uplink confirmé : le downlink porte le bit ACK (ACK seul si la file est vide).

Downlinks : un seul par uplink, émis en RX1 à rxpk.tmst + 1 s, sur le canal et au débit RX1 du
plan régional (`lsim.plan` : EU868 même canal ; US915 canal modulo 8, RX1DROffset 0). Les compteurs NFCntDown / AFCntDown ne sont
consommés que si le downlink est effectivement produit, dans la transaction de l'uplink.
Livraison au mieux : un downlink est retiré de la file à l'émission ; il n'y a pas de
retransmission. Un downlink confirmé attend l'acquittement : l'uplink suivant (ACK ou non)
le clôt. Sans acquittement, il est considéré non reçu et n'est pas renvoyé (limite documentée).

Retransmission d'un uplink confirmé déjà accepté (delta 0, MIC valide) : ACK seul renvoyé,
sans nouvelle livraison ni changement d'état. Un uplink non confirmé répété est rejeté.

Commandes MAC à acquitter (`mac_pending`) : renvoyées en FOpts à chaque downlink jusqu'au
LinkADRAns du dispositif, au plus MAC_MAX_ATTEMPTS fois. FPending et ADR ne sont pas interprétés. Les
charges de FPort > 0 sans AppKey ne sont pas déchiffrables et ne sont pas livrées.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

import logging

from lsim import mac
from lsim.gwmp import Rxpk, Txpk
from lsim.join_store import MAC_MAX_ATTEMPTS, DurableJoinStore, QueueItem, Transaction
from lsim.lora import StatusError
from lsim.plan import RECEIVE_DELAY1_US, Plan, get_plan
from lsim.security import (
    DownlinkContext, UplinkContext, UplinkFrame, open_uplink, seal_downlink,
)

MTYPE_UNCONFIRMED_UP = 0b010
MTYPE_CONFIRMED_UP = 0b100
MTYPE_JOIN_REQUEST = 0b000
MTYPE_REJOIN_REQUEST = 0b110
_MIN_FRAME_LEN = 12          # MHDR, DevAddr, FCtrl, FCnt, MIC
_ACK_BIT = 0x20              # FCtrl.ACK en uplink
_COUNTER32_LIMIT = 0xFFFFFFFF
_FOPTS_MAX = 15
CID_LINK_ADR = 0x03          # LinkADRReq / LinkADRAns
_log = logging.getLogger("lsim.uplink")


def _acked_cids(fopts: bytes) -> set[int]:
    """CID des commandes acquittées dans les FOpts montants (LinkADRAns : trois bits à 1)."""
    if not fopts:
        return set()
    try:
        answers = mac.decode_all(fopts, downlink=False)
    except (ValueError, StatusError):
        return set()
    acked: set[int] = set()
    for answer in answers:
        if isinstance(answer, mac.LinkAdrAns) and answer.channel_mask_ack \
                and answer.data_rate_ack and answer.power_ack:
            acked.add(CID_LINK_ADR)
    return acked


def _pending_fopts(tx: Transaction, dev_eui: bytes) -> tuple[bytes, list[int]]:
    """FOpts des commandes à renvoyer : au plus 15 octets, en abandonnant les épuisées."""
    fopts = b""
    sent: list[int] = []
    for item in tx.pending_mac(dev_eui):
        if item.attempts >= MAC_MAX_ATTEMPTS:
            tx.mac_done(dev_eui, item.cid)
            _log.warning("commande MAC %d non acquittée après %d essais : abandon",
                         item.cid, item.attempts)
            continue
        if len(fopts) + len(item.command) <= _FOPTS_MAX:
            fopts += item.command
            sent.append(item.cid)
    return fopts, sent


@dataclass(frozen=True)
class Outcome:
    """Résultat du traitement d'un paquet : issue (pour les statistiques), downlink, livraison."""
    issue: str
    txpk: Optional[Txpk] = None
    delivery: Optional["Delivery"] = None
    dev_eui: Optional[bytes] = None      # dispositif concerné par le downlink (Basic Station : DevEui)


@dataclass(frozen=True)
class Delivery:
    """Uplink de données accepté, prêt pour l'application. payload None : non déchiffrable/non traité."""
    dev_eui: bytes
    dev_addr: int
    fcnt: int                 # compteur 32 bits reconstruit
    confirmed: bool
    fport: Optional[int]
    payload: Optional[bytes] = field(repr=False)
    fopts: bytes = field(repr=False)


class Handler(Protocol):
    def handle(self, rxpk: Rxpk) -> Outcome: ...


class _Reject(Exception):
    """Rejet : la transaction est annulée, rien n'est persisté."""

    def __init__(self, issue: str) -> None:
        super().__init__(issue)
        self.issue = issue


def reconstruct_fcnt32(last: int, fcnt16: int) -> tuple[int, bool]:
    """Compteur 32 bits à partir du dernier accepté (-1 : aucun) et du FCnt 16 bits.

    Retourne (compteur, retransmission). Delta 0 = même compteur que la dernière trame.
    """
    if last < 0:
        return fcnt16, False
    delta = (fcnt16 - (last & 0xFFFF)) & 0xFFFF
    if delta == 0:
        return last, True
    return last + delta, False


class DataUplinkHandler:
    """Traite les uplinks de données EU868 ; persiste dans le même magasin que la jointure."""

    def __init__(self, store: DurableJoinStore, plan: Optional[Plan] = None) -> None:
        self._store = store
        self._plan = plan if plan is not None else get_plan("EU868")

    def handle(self, rxpk: Rxpk) -> Outcome:
        wire = rxpk.payload
        if len(wire) < _MIN_FRAME_LEN or len(wire) > 255:
            return Outcome("invalid")
        if (wire[0] >> 5) not in (MTYPE_UNCONFIRMED_UP, MTYPE_CONFIRMED_UP):
            return Outcome("data_unhandled")
        try:
            tx_dr = self._plan.data_rate_index(rxpk.datr)
            tx_ch = self._plan.channel_index(rxpk.freq_mhz)
            rx1 = self._plan.rx1(tx_dr, tx_ch)
        except ValueError:
            return Outcome("data_unsupported_channel")
        dev_addr = int.from_bytes(wire[1:5], "little")
        ack = bool(wire[5] & _ACK_BIT)
        fcnt16 = int.from_bytes(wire[6:8], "little")
        try:
            with self._store.transaction() as tx:
                return self._process(tx, rxpk, wire, dev_addr, ack, fcnt16, tx_dr, tx_ch, rx1)
        except _Reject as rej:
            return Outcome(rej.issue)

    def _process(self, tx: Transaction, rxpk: Rxpk, wire: bytes, dev_addr: int, ack: bool,
                 fcnt16: int, tx_dr: int, tx_ch: int, rx1: tuple[float, str]) -> Outcome:
        rec = tx.session_by_addr(dev_addr)
        fresh = False   # contexte issu d'un rejoin, en attente de son premier uplink valide
        if rec is None:
            rec = tx.pending_by_addr(dev_addr)
            if rec is None:
                raise _Reject("data_unknown_addr")
            fresh = True
        cand, retrans = reconstruct_fcnt32(rec.fcnt_up, fcnt16)
        if cand > _COUNTER32_LIMIT:
            raise _Reject("data_counter_exhausted")
        conf = (rec.pending_conf & 0xFFFF) if (ack and rec.pending_conf is not None) else 0
        try:
            frame = open_uplink(wire, rec.keys, UplinkContext(
                fcnt32=cand, conf_fcnt=conf, tx_dr=tx_dr, tx_ch=tx_ch))
        except (StatusError, ValueError):
            raise _Reject("data_replay" if retrans else "data_mic_failed") from None
        if fresh:
            # Premier uplink valide du nouveau contexte : l'ancien est abandonné (1.1 §6.2.4).
            # Dans la transaction : un rejet ultérieur annule aussi cette promotion.
            rec = tx.promote_pending(rec.dev_eui)

        if retrans:
            if not frame.confirmed:
                raise _Reject("data_replay")
            # Retransmission d'un confirmé déjà accepté : seul l'acquittement est renvoyé.
            # Aucun changement d'état hormis le compteur NFCntDown consommé par l'ACK.
            txpk, sent = _build_downlink(rxpk, rec, rx1, ack_for=cand, send=None,
                                         max_payload=self._plan.queue_payload_max)
            _save(tx, rec, fcnt_up=rec.fcnt_up, pending=rec.pending_conf, sent=sent)
            return Outcome("data_ack_repeated", txpk=txpk, dev_eui=rec.dev_eui)

        for cid in _acked_cids(frame.fopts):
            tx.mac_done(rec.dev_eui, cid)
        # Rejoin en attente : downlinks et commandes MAC partent seulement sur le nouveau
        # contexte. Un uplink sur l'ancien n'en reçoit que l'acquittement (confirmé).
        held = tx.pending_by_eui(rec.dev_eui) is not None
        mac_fopts, mac_sent = (b"", []) if held else _pending_fopts(tx, rec.dev_eui)

        fport = frame.fport
        payload = frame.payload if (fport is not None and fport > 0 and rec.has_app_key) else None
        delivery = Delivery(dev_eui=rec.dev_eui, dev_addr=dev_addr, fcnt=cand,
                            confirmed=frame.confirmed, fport=fport, payload=payload,
                            fopts=frame.fopts)
        head = None if held else tx.queue_head(rec.dev_eui)
        txpk = None
        sent = None
        if head is not None or frame.confirmed or mac_fopts:
            txpk, sent = _build_downlink(
                rxpk, rec, rx1, ack_for=cand if frame.confirmed else None, send=head,
                max_payload=self._plan.queue_payload_max, fopts=mac_fopts)
            if head is not None:
                tx.dequeue(head.seq)
            for cid in mac_sent:
                tx.mac_attempted(rec.dev_eui, cid)
        # Nouvelle trame valide : toute confirmation en attente est close (acquittée ou perdue).
        # Un downlink confirmé émis ici devient la confirmation attendue de l'uplink suivant.
        pending = sent.counter if (sent is not None and sent.confirmed) else None
        _save(tx, rec, fcnt_up=cand, pending=pending, sent=sent)
        return Outcome("data_accepted", txpk=txpk, delivery=delivery, dev_eui=rec.dev_eui)


@dataclass(frozen=True)
class _Sent:
    """Downlink produit : compteur 32 bits consommé, type (AFCnt pour FPort > 0), confirmé."""
    counter: int
    af: bool
    confirmed: bool


def _build_downlink(rxpk: Rxpk, rec, rx1: tuple[float, str], ack_for: Optional[int],
                    send: Optional[QueueItem], max_payload: int,
                    fopts: bytes = b"") -> tuple[Txpk, _Sent]:
    """Chiffre et signe le downlink, sans rien persister. RX1 : tmst + 1 s, canal et débit du plan."""
    fport = send.fport if send is not None else None
    payload = send.payload if send is not None else b""
    if len(payload) > max_payload:
        # Impossible par construction : la file refuse les charges au-dessus de queue_payload_max.
        raise ValueError("charge en file au-delà de la limite du plan")
    af = fport is not None and fport > 0
    counter = rec.afcnt_down if af else rec.nfcnt_down
    confirmed = bool(send is not None and send.confirmed)
    frame = UplinkFrame(
        dev_addr=rec.dev_addr, fcnt=counter & 0xFFFF, payload=payload, fport=fport,
        confirmed=confirmed, ack=ack_for is not None, fopts=fopts)
    wire_dl = seal_downlink(frame, rec.keys, DownlinkContext(
        conf_fcnt=(ack_for & 0xFFFF) if ack_for is not None else 0,
        nfcnt32=rec.nfcnt_down, afcnt32=rec.afcnt_down))
    rx1_freq, rx1_datr = rx1
    txpk = Txpk(tmst=(rxpk.tmst + RECEIVE_DELAY1_US) % (2**32), freq_mhz=rx1_freq,
                datr=rx1_datr, codr=rxpk.codr, payload=wire_dl)
    return txpk, _Sent(counter=counter, af=af, confirmed=confirmed)


def _save(tx: Transaction, rec, fcnt_up: int, pending: Optional[int],
          sent: Optional[_Sent]) -> None:
    """Écrit l'état final en une fois : compteur montant, confirmation en attente, compteur consommé."""
    nf, af = rec.nfcnt_down, rec.afcnt_down
    if sent is not None:
        if sent.af:
            af = sent.counter + 1
        else:
            nf = sent.counter + 1
    if nf > _COUNTER32_LIMIT or af > _COUNTER32_LIMIT:
        raise _Reject("downlink_counter_exhausted")
    tx.save_counters(rec.dev_addr, fcnt_up, nf, af, pending)


class UplinkRouter:
    """Route les paquets : join-request / rejoin vers le serveur de jointure, données vers le gestionnaire."""

    def __init__(self, join_handler: Handler, data_handler: Handler) -> None:
        self._join = join_handler
        self._data = data_handler

    def handle(self, rxpk: Rxpk) -> Outcome:
        if rxpk.payload and (rxpk.payload[0] >> 5) in (MTYPE_UNCONFIRMED_UP, MTYPE_CONFIRMED_UP):
            return self._data.handle(rxpk)
        return self._join.handle(rxpk)

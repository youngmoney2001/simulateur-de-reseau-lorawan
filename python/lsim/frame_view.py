"""Vue par couches des trames LoRaWAN d'une trace (inspecteur de trames).

Ce module est **additif** : il ne modifie ni `ProtocolEvent`, ni la trace, ni l'ABI. Il part
d'une trace déjà calculée et reconstruit, pour chaque événement, la trame PHY que le dispositif
aurait émise, puis la décompose par couche — l'équivalent des vues *OSI Model* et *Detailed PDU*
d'un inspecteur de réseau.

Les octets sont **réels** : l'assemblage, le chiffrement de la charge et le calcul du MIC sont
faits par le cœur C++ (`lsim_seal_uplink`), via `lsim.security`. Ce module n'implémente donc
aucune cryptographie et ne réécrit aucune règle déjà testée.

Portée de la fidélité — à lire avant d'enseigner avec ces trames
---------------------------------------------------------------
La trame est **structurellement exacte** : MHDR, FHDR, FCtrl, FCnt, FPort, FRMPayload et MIC
occupent leurs positions normatives, le chiffrement et le MIC sont ceux de la spécification.

Deux valeurs ne viennent pas d'un Join réel, parce que le chemin historique de la trace ne
modélise pas de session :

* **DevAddr** : dérivé de la graine du scénario et de l'indice du dispositif ;
* **clés de session** : dérivées de la même graine (`derive_session_keys_11`).

Elles sont donc **synthétiques mais déterministes** : deux exécutions du même scénario produisent
les mêmes octets, ce qui est la propriété utile en classe. Ce n'est en revanche pas la preuve
qu'un réseau réel attribuerait ces valeurs. Conformité de la forme, fidélité moyenne sur
l'identité — au sens où un simulateur pédagogique assume une fidélité moyenne.

Le compteur de trame est celui de la simulation : `FCnt` est le rang du message pour ce
dispositif (16 bits sur l'air, série 32 bits dans le contexte de MIC).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

from lsim.security import (MAX_FRM_PAYLOAD, SessionKeys11, UplinkContext, UplinkFrame,
                           derive_session_keys_11, seal_uplink)

__all__ = [
    "DeviceSession",
    "FrameView",
    "build_uplink_wire",
    "derive_session",
    "describe",
    "frames_for_run",
    "MTYPE_NAMES",
]

# --- Types de message (MHDR, bits 7:5) -------------------------------------------------------

MTYPE_NAMES = {
    0b000: "join_request",
    0b001: "join_accept",
    0b010: "unconfirmed_data_up",
    0b011: "unconfirmed_data_down",
    0b100: "confirmed_data_up",
    0b101: "confirmed_data_down",
    0b110: "rejoin_request",
    0b111: "proprietary",
}

_MAJOR_NAMES = {0b00: "LoRaWAN R1"}

_MHDR_LEN = 1
_FHDR_LEN = 7          # DevAddr(4) + FCtrl(1) + FCnt(2), FOpts exclu
_MIC_LEN = 4


def _derive(seed: int, device_index: int, what: str, size: int) -> bytes:
    """Octets déterministes : mêmes entrées, mêmes octets, sur toute machine."""
    msg = f"lsim-frame-v1|{seed}|{device_index}|{what}".encode("utf-8")
    return hashlib.blake2b(msg, digest_size=size).digest()


@dataclass(frozen=True)
class DeviceSession:
    """Identité et clés d'un dispositif, dérivées de la graine du scénario.

    Voir l'en-tête du module : valeurs synthétiques, déterministes, non issues d'un Join.
    """

    dev_addr: int
    keys: SessionKeys11


def derive_session(seed: int, device_index: int) -> DeviceSession:
    """Session d'un dispositif, fonction de la graine et de son indice seulement."""
    if seed < 0 or device_index < 0:
        raise ValueError("graine et indice de dispositif doivent être positifs")
    dev_addr = int.from_bytes(_derive(seed, device_index, "devaddr", 4), "little")
    nwk_key = _derive(seed, device_index, "nwkkey", 16)
    app_key = _derive(seed, device_index, "appkey", 16)
    join_nonce = _derive(seed, device_index, "joinnonce", 3)
    join_eui = _derive(seed, device_index, "joineui", 8)
    dev_nonce = _derive(seed, device_index, "devnonce", 2)
    keys = derive_session_keys_11(nwk_key=nwk_key, app_key=app_key, join_nonce=join_nonce,
                                  join_eui=join_eui, dev_nonce=dev_nonce)
    return DeviceSession(dev_addr=dev_addr, keys=keys)


def build_uplink_wire(session: DeviceSession, *, fcnt32: int, payload: bytes,
                      fport: Optional[int] = 1, confirmed: bool = False, adr: bool = False,
                      ack: bool = False, tx_dr: int = 0, tx_ch: int = 0) -> bytes:
    """Trame PHY montante complète : assemblage, chiffrement et MIC par le cœur C++.

    `fport=None` : trame sans port ni charge (commandes MAC seules) — la charge doit être vide.
    """
    if len(payload) > MAX_FRM_PAYLOAD:
        raise ValueError(f"charge limitée à {MAX_FRM_PAYLOAD} octets (reçu {len(payload)})")
    if fport is None and payload:
        raise ValueError("une charge sans FPort est interdite")
    frame = UplinkFrame(dev_addr=session.dev_addr, fcnt=fcnt32 & 0xFFFF, payload=payload,
                        fport=fport, confirmed=confirmed, adr=adr, ack=ack)
    ctx = UplinkContext(fcnt32=fcnt32 & 0xFFFFFFFF, tx_dr=tx_dr, tx_ch=tx_ch)
    return seal_uplink(frame, session.keys, ctx)


@dataclass(frozen=True)
class FrameView:
    """Trame décomposée, prête à afficher couche par couche."""

    wire: bytes
    mtype: int
    mtype_name: str
    major: int
    major_name: str
    dev_addr: int
    fctrl: int
    fcnt: int
    fopts: bytes
    fport: Optional[int]
    frm_payload: bytes
    mic: bytes

    # --- Drapeaux de FCtrl ---------------------------------------------------------------

    @property
    def adr(self) -> bool:
        return bool(self.fctrl & 0x80)

    @property
    def adr_ack_req(self) -> bool:
        return bool(self.fctrl & 0x40)

    @property
    def ack(self) -> bool:
        return bool(self.fctrl & 0x20)

    @property
    def f_pending(self) -> bool:
        """En montante ce bit est `ClassB` ; en descendante il devient `FPending`."""
        return bool(self.fctrl & 0x10)

    @property
    def fopts_len(self) -> int:
        return self.fctrl & 0x0F

    # --- Présentation --------------------------------------------------------------------

    @property
    def taille_totale(self) -> int:
        return len(self.wire)

    def couches(self) -> dict[str, dict[str, Any]]:
        """Décomposition par couche, pour un affichage à la façon d'un inspecteur."""
        return {
            "phy": {
                "octets": self.taille_totale,
                "contenu_hex": self.wire.hex(),
            },
            "mac": {
                "mhdr_hex": self.wire[:1].hex(),
                "mtype": self.mtype_name,
                "major": self.major_name,
                "dev_addr_hex": f"{self.dev_addr:08X}",
                "fctrl_hex": f"{self.fctrl:02X}",
                "adr": self.adr,
                "adr_ack_req": self.adr_ack_req,
                "ack": self.ack,
                "f_pending_ou_class_b": self.f_pending,
                "fopts_len": self.fopts_len,
                "fopts_hex": self.fopts.hex(),
                "fcnt": self.fcnt,
                "mic_hex": self.mic.hex(),
            },
            "application": {
                "fport": self.fport,
                "frm_payload_octets": len(self.frm_payload),
                "frm_payload_hex": self.frm_payload.hex(),
            },
        }

    def lignes(self) -> tuple[str, ...]:
        """Trame en lignes lisibles, destinées à une console ou à un journal."""
        out = [
            f"PHY      {self.taille_totale} octets  {self.wire.hex()}",
            f"MHDR     {self.wire[:1].hex()}  {self.mtype_name} / {self.major_name}",
            f"DevAddr  {self.dev_addr:08X}",
            f"FCtrl    {self.fctrl:02X}  "
            f"ADR={int(self.adr)} ADRACKReq={int(self.adr_ack_req)} "
            f"ACK={int(self.ack)} FPending/ClassB={int(self.f_pending)} "
            f"FOptsLen={self.fopts_len}",
            f"FCnt     {self.fcnt}",
        ]
        if self.fopts:
            out.append(f"FOpts    {self.fopts.hex()}")
        if self.fport is None:
            out.append("FPort    (absent : commandes MAC seules)")
        else:
            out.append(f"FPort    {self.fport}")
            out.append(f"Charge   {len(self.frm_payload)} octets  {self.frm_payload.hex()}")
        out.append(f"MIC      {self.mic.hex()}")
        return tuple(out)


def describe(wire: bytes) -> FrameView:
    """Décompose une trame de données déjà assemblée.

    Ne vérifie pas le MIC (cela demande les clés) : c'est une lecture de forme, pas une
    validation cryptographique. Lever une erreur sur une trame courte évite de rendre une
    décomposition fausse.
    """
    if not isinstance(wire, (bytes, bytearray)):
        raise ValueError("la trame doit être de type bytes")
    wire = bytes(wire)
    mini = _MHDR_LEN + _FHDR_LEN + _MIC_LEN
    if len(wire) < mini:
        raise ValueError(f"trame trop courte : {len(wire)} octets, minimum {mini}")

    mhdr = wire[0]
    mtype = mhdr >> 5
    major = mhdr & 0x03
    fctrl = wire[5]
    fopts_len = fctrl & 0x0F

    debut_fopts = _MHDR_LEN + _FHDR_LEN
    fin_fopts = debut_fopts + fopts_len
    if fin_fopts + _MIC_LEN > len(wire):
        raise ValueError("FOpts annoncés par FCtrl au-delà de la trame")

    apres_fopts = wire[fin_fopts:-_MIC_LEN]
    fport: Optional[int]
    if apres_fopts:
        fport = apres_fopts[0]
        frm_payload = apres_fopts[1:]
    else:
        fport, frm_payload = None, b""

    return FrameView(
        wire=wire,
        mtype=mtype,
        mtype_name=MTYPE_NAMES.get(mtype, "inconnu"),
        major=major,
        major_name=_MAJOR_NAMES.get(major, "inconnu"),
        dev_addr=int.from_bytes(wire[1:5], "little"),
        fctrl=fctrl,
        fcnt=int.from_bytes(wire[6:8], "little"),
        fopts=wire[debut_fopts:fin_fopts],
        fport=fport,
        frm_payload=frm_payload,
        mic=wire[-_MIC_LEN:],
    )


# --- Reconstruction pour une trace entière ---------------------------------------------------

_UPLINK_KINDS = {"uplink", "retransmission"}
_CONFIRMED_OUTCOMES = frozenset()  # le caractère confirmé vient du scénario, pas de l'issue


def frames_for_run(run: Any, scenario: Any) -> tuple[Optional[FrameView], ...]:
    """Une trame par événement de la trace ; `None` pour ceux qui n'en portent pas.

    Seuls les uplinks de données portent une trame montante : les ACK, les descentes, les
    fenêtres manquées et les événements MAC ne sont pas des émissions de dispositif. Rendre
    `None` plutôt qu'une trame inventée est le choix honnête.

    Le rang du message par dispositif fournit `FCnt` — c'est le compteur de la simulation,
    remis à zéro à chaque exécution, comme la trace elle-même.
    """
    radios = tuple(scenario.model.groups)  # groupes, dans l'ordre du scénario
    by_name = {g.name: g for g in radios}
    devices, group_of, _ = scenario.deploy()
    seed = int(scenario.model.seed)

    payload_of: list[bytes] = []
    confirmed_of: list[bool] = []
    adr_of: list[bool] = []
    for name in group_of:
        g = by_name.get(name)
        if g is None:  # groupe inconnu : pas de trame plutôt qu'une hypothèse
            payload_of.append(b"")
            confirmed_of.append(False)
            adr_of.append(False)
            continue
        n = min(int(g.payload_bytes), MAX_FRM_PAYLOAD)
        payload_of.append(_derive(seed, len(payload_of), "payload", n) if n else b"")
        mac = scenario.model.mac
        adr_of.append(bool(mac is not None and getattr(mac, "adr", False)))
        confirmed_of.append(bool(scenario.model.retransmissions is not None))

    compteur: dict[int, int] = {}
    vues: list[Optional[FrameView]] = []
    for ev in run.events:
        if ev.kind not in _UPLINK_KINDS or ev.device_index >= len(payload_of):
            vues.append(None)
            continue
        d = ev.device_index
        rang = compteur.get(d, 0)
        compteur[d] = rang + 1
        session = derive_session(seed, d)
        try:
            wire = build_uplink_wire(
                session,
                fcnt32=rang,
                payload=payload_of[d],
                fport=1 if payload_of[d] else None,
                confirmed=confirmed_of[d],
                adr=adr_of[d],
                tx_dr=0,
            )
        except ValueError:
            vues.append(None)
            continue
        vues.append(describe(wire))
    return tuple(vues)

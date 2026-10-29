"""Bloc `mac:` → boucle fermée (LinkADRReq et DutyCycleReq) : paramètres du moteur natif.

Actif seulement si le scénario demande `link_adr` ou `duty_cycle_exponent`. Sans ces champs, les
scénarios gardent le chemin existant (résultats et empreintes inchangés).

Périmètre : passerelle unique, sans jointure. Les réservations MAC (LinkCheckReq, DeviceTimeReq,
DevStatusAns) suivent le calendrier de `mac_plan` : octets dans l'airtime, réponses dans les
descentes qui répondent aux uplinks reçus. Les combinaisons hors périmètre sont refusées
explicitement.

Règles de puissance et de duty cycle (voir docs/CLOSED_LOOP_PLAN.md, S2) :
- index 0 = puissance configurée, plafonnée par la PIRE du plan (`regions.POWER_TABLES`) ; chaque
  index retire le pas du plan ; les index réservés par le plan sont refusés par LinkADR ;
- limite réglementaire par index = sous-bande la plus restrictive à la PIRE de cet index,
  combinée au duty cycle du groupe (`min`). DutyCycleReq ne fait que la réduire ;
- un plan sans table TXPower n'accepte pas LinkADR (aucune puissance inventée).
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence

from lsim import mac_plan
from lsim.closed_loop import (
    ANSWER_DEVICE_STATUS, MAC_DEVICE_STATUS, MAC_DEVICE_TIME, MAC_LINK_CHECK, LoopOptions,
    LoopRegion, MacByteAccounting, MacSlot,
)
from lsim.mac import DeviceTimeReq, LinkCheckReq
from lsim.mac_plan import MacSchedule
from lsim.plan import get_plan
from lsim.regions import PROFILES, power_table


def closed_loop_applies(scenario) -> bool:
    """Vrai si le bloc `mac:` demande LinkADR ou DutyCycle (boucle fermée)."""
    m = scenario.model.mac
    return m is not None and (m.link_adr or m.duty_cycle_exponent is not None)


def check_closed_loop(scenario, options: Any) -> None:
    """Refuse explicitement les combinaisons hors périmètre de la boucle fermée (ValueError)."""
    if getattr(options, "join", False):
        raise ValueError("LinkADR/DutyCycle : jointure non supportée par la boucle fermée")
    if scenario.model.gateways is not None or scenario.model.mesh is not None:
        raise ValueError("LinkADR/DutyCycle : passerelle unique uniquement "
                         "(pas de « gateways » ni de mesh)")


def mac_slots(schedule: Optional[MacSchedule], devices: Sequence) -> tuple[MacSlot, ...]:
    """Calendrier MAC de la boucle fermée : une entrée par émission réservée ou portante.

    Les octets réservés sont ceux de `mac_plan.reserved_extra_bytes` (même calendrier que le
    chemin historique). Les drapeaux suivent les requêtes du calendrier : LinkCheckAns et
    DeviceTimeAns répondent à un uplink reçu de rang demandé, DevStatusReq est due dans le
    downlink répondant à l'uplink de rang indiqué.
    """
    if schedule is None:
        return ()
    out: list[MacSlot] = []
    for i, d in enumerate(devices):
        for rank in range(1, d.messages + 1):
            extra = mac_plan.reserved_extra_bytes(schedule, rank)
            requests = mac_plan.uplink_requests(schedule, rank)
            flags = 0
            if LinkCheckReq() in requests:
                flags |= MAC_LINK_CHECK
            if DeviceTimeReq() in requests:
                flags |= MAC_DEVICE_TIME
            if mac_plan.device_status_request_due(schedule, rank):
                flags |= MAC_DEVICE_STATUS
            if extra or flags:
                out.append(MacSlot(device=i, rank=rank, extra_bytes=extra, flags=flags))
    return tuple(out)


def loop_options(scenario, options: Any) -> LoopOptions:
    m = scenario.model.mac
    return LoopOptions(
        confirmed_uplinks=options.confirmed_uplinks,
        downlink_every=options.downlink_every,
        downlink_payload_bytes=options.downlink_payload_bytes,
        gateway_tx_power_dbm=options.gateway_tx_power_dbm,
        device_antenna_gain_dbi=options.device_antenna_gain_dbi,
        device_rx_offset_db=options.device_rx_offset_db,
        adr=m.link_adr,
        installation_margin_tenth_db=m.link_margin_installation_db * 10,
        duty_cycle=m.duty_cycle_exponent is not None,
        duty_cycle_exponent=m.duty_cycle_exponent or 0,
    )


def _group_region(g, link_adr: bool) -> LoopRegion:
    """Paramètres régionaux d'un groupe (partagés par tous ses dispositifs)."""
    tx = g.tx_power_dbm
    if g.region is None:
        if link_adr:
            raise ValueError(f"groupe {g.name!r} : LinkADR exige un plan régional")
        return LoopRegion(dr_sf=(0,) * 16, max_dr=0, max_tx_power_index=0,
                          power_step_tenth_db=20, max_eirp_dbm=math.inf,
                          duty_limit=(g.duty_cycle,) + (1.0,) * 15)

    try:
        plan = get_plan(g.region)
    except ValueError as exc:
        raise ValueError(f"groupe {g.name!r} : {exc}") from exc
    dr_sf = [0] * 16
    for i, (sf, bw_khz, _) in enumerate(plan.dr_table()[:16]):
        if bw_khz == 125:
            dr_sf[i] = sf
    usable = [i for i, s in enumerate(dr_sf) if s]
    max_dr = max(usable) if usable else 0
    if link_adr and g.spreading_factor not in dr_sf:
        raise ValueError(f"groupe {g.name!r} : SF {g.spreading_factor} absent des débits 125 kHz "
                         f"du plan {g.region}")

    table = power_table(g.region)
    if link_adr and table is None:
        raise ValueError(f"groupe {g.name!r} : plan {g.region} sans table TXPower, LinkADR refusé")
    if table is not None and tx > table.max_eirp_dbm:
        raise ValueError(f"groupe {g.name!r} : puissance {tx} dBm au-dessus de la PIRE du plan "
                         f"({table.max_eirp_dbm} dBm)")
    max_eirp = table.max_eirp_dbm if table is not None else math.inf
    step_db = table.step_db if table is not None else 2.0
    max_index = table.max_index if table is not None else 0
    profile = PROFILES.get(g.region)
    duty = [1.0] * 16
    for i in range(max_index + 1):
        eirp = min(tx, max_eirp) - i * step_db
        limit = profile.duty_cycle_limit(g.channel_freq_hz, eirp) if profile is not None else None
        duty[i] = g.duty_cycle if limit is None else min(g.duty_cycle, limit)
    return LoopRegion(dr_sf=tuple(dr_sf), max_dr=max_dr, max_tx_power_index=max_index,
                      power_step_tenth_db=round(step_db * 10),
                      max_eirp_dbm=max_eirp, duty_limit=tuple(duty))


# Tailles des réponses portées par un uplink (identiques à `answer_octets` du moteur).
LINK_ADR_ANS_BYTES = 2
DUTY_CYCLE_ANS_BYTES = 1


def mac_byte_accounting(schedule: Optional[MacSchedule], devices: Sequence,
                        uplinks: Sequence) -> MacByteAccounting:
    """Comptabilité des octets MAC d'une boucle fermée (voir `MacByteAccounting`).

    `uplinks` : `LoopOutcome.uplinks`, dans l'ordre temporel (rang = ordre par dispositif).
    """
    if schedule is None:
        return MacByteAccounting(0, 0, 0, 0, 0, 0)
    reserved = 0
    reserved_ds = 0
    for d in devices:
        for rank in range(1, d.messages + 1):
            reserved += mac_plan.reserved_extra_bytes(schedule, rank)
            if rank >= 2 and mac_plan.device_status_request_due(schedule, rank - 1):
                reserved_ds += mac_plan.DEVICE_STATUS_ANS_BYTES
    sent = 0
    sent_ds = 0
    confirmed = 0
    rank_of: dict[int, int] = {}
    for u in uplinks:
        rank = rank_of.get(u.device, 0) + 1
        rank_of[u.device] = rank
        if u.answer_mask & 1:
            sent += LINK_ADR_ANS_BYTES
        if u.answer_mask & 2:
            sent += DUTY_CYCLE_ANS_BYTES
        for cmd in mac_plan.uplink_requests(schedule, rank):
            sent += (mac_plan.LINK_CHECK_REQ_BYTES if isinstance(cmd, LinkCheckReq)
                     else mac_plan.DEVICE_TIME_REQ_BYTES)
        if u.answer_mask & ANSWER_DEVICE_STATUS:
            sent += mac_plan.DEVICE_STATUS_ANS_BYTES
            sent_ds += mac_plan.DEVICE_STATUS_ANS_BYTES
            if u.outcome == "received":
                confirmed += 1
    return MacByteAccounting(
        reserved_bytes=reserved, reserved_ds_bytes=reserved_ds, sent_bytes=sent,
        sent_ds_bytes=sent_ds, unused_reserved_ds_bytes=reserved_ds - sent_ds,
        confirmed_ds_answers=confirmed)


def loop_regions(scenario, group_of: Sequence[str]) -> list[LoopRegion]:
    """Un `LoopRegion` par dispositif, dans l'ordre de `Scenario.deploy`."""
    link_adr = scenario.model.mac.link_adr
    by_name = {g.name: g for g in scenario.model.groups}
    cache: dict[str, LoopRegion] = {}
    out = []
    for name in group_of:
        if name not in cache:
            cache[name] = _group_region(by_name[name], link_adr)
        out.append(cache[name])
    return out

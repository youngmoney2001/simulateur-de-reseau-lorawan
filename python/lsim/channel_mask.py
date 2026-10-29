"""Sous-bandes et masques de canaux LinkADRReq pour US915 et AU915.

Règle (LoRaWAN RP002-1.0.3 §2.5.3 pour US915, RP002-1.0.2 §2.8.5 pour AU915) :
- ChMaskCntl 0 à 3 : ChMask (16 bits) couvre les canaux 125 kHz 16·k à 16·k+15 ;
- ChMaskCntl 4 : ChMask couvre les canaux 500 kHz 64 à 71 (bit i = canal 64+i) ;
- ChMaskCntl 5 : chaque bit b (0 à 7) active ou désactive une banque : les canaux 125 kHz
  8·b à 8·b+7 et le canal 500 kHz 64+b ; bits 8 à 15 RFU ;
- ChMaskCntl 6 : tous les canaux 125 kHz (0 à 63) activés ; ChMask couvre les canaux 64 à 71 ;
- ChMaskCntl 7 : tous les canaux 125 kHz désactivés ; ChMask couvre les canaux 64 à 71 ;
- Les bits de ChMask hors de la portée utile de chaque ChMaskCntl doivent être nuls (sinon rejet).

Une sous-bande n (1 à 8) regroupe les canaux 125 kHz 8·(n−1) à 8·(n−1)+7 et le canal 500 kHz 64+(n−1).
Un LinkADRReq avec ChMaskCntl = 5 et ChMask = 1 << (n−1) sélectionne exactement cette sous-bande.

Hors périmètre : EU868 (ChMaskCntl 0 seulement, 16 canaux) et les masques lus d'un CFList.
"""

from __future__ import annotations

from typing import Optional

FAMILY = ("US915", "AU915")          # plans partageant cette règle de masque
SUB_BAND_COUNT = 8
CHANNEL_COUNT = 72                   # 64 × 125 kHz (0-63) + 8 × 500 kHz (64-71)
_LAST_125 = 63
_FIRST_500 = 64

_UINT16_MAX = 0xFFFF


def _check_family(plan_name: str) -> None:
    if plan_name not in FAMILY:
        raise ValueError(f"sous-bandes non définies pour le plan {plan_name!r}")


def all_channels() -> frozenset[int]:
    """Configuration par défaut : canaux 0 à 71 actifs (join-request sur les 72 canaux)."""
    return frozenset(range(CHANNEL_COUNT))


def sub_band_channels(n: int) -> frozenset[int]:
    """Canaux de la sous-bande n (1 à 8) : 8 canaux 125 kHz et 1 canal 500 kHz."""
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= SUB_BAND_COUNT:
        raise ValueError(f"sous-bande hors plage 1..{SUB_BAND_COUNT} : {n!r}")
    bank = n - 1
    return frozenset(range(8 * bank, 8 * bank + 8)) | {_FIRST_500 + bank}


def link_adr_for_sub_band(n: int) -> tuple[int, int]:
    """(ChMask, ChMaskCntl) d'un LinkADRReq qui ne laisse actif que la sous-bande n."""
    sub_band_channels(n)                       # validation
    return 1 << (n - 1), 5


def sub_band_of(channel: int) -> Optional[int]:
    """Sous-bande d'un canal d'indice 0 à 71 ; None si hors plage."""
    if 0 <= channel <= _LAST_125:
        return channel // 8 + 1
    if _FIRST_500 <= channel < CHANNEL_COUNT:
        return channel - _FIRST_500 + 1
    return None


def _validate_mask(ch_mask: int, ch_mask_cntl: int) -> None:
    if not isinstance(ch_mask, int) or isinstance(ch_mask, bool) or not 0 <= ch_mask <= _UINT16_MAX:
        raise ValueError(f"ChMask hors 16 bits : {ch_mask!r}")
    if not isinstance(ch_mask_cntl, int) or isinstance(ch_mask_cntl, bool) \
            or not 0 <= ch_mask_cntl <= 7:
        raise ValueError(f"ChMaskCntl hors 0..7 : {ch_mask_cntl!r}")
    if ch_mask_cntl == 5 and ch_mask >> 8:
        raise ValueError("ChMaskCntl 5 : bits 8 à 15 de ChMask réservés (RFU)")
    if ch_mask_cntl in (4, 6, 7) and ch_mask >> 8:
        raise ValueError(f"ChMaskCntl {ch_mask_cntl} : seuls les 8 bits bas de ChMask sont utilisés")


def apply_link_adr(plan_name: str, enabled: frozenset[int], ch_mask: int,
                   ch_mask_cntl: int) -> frozenset[int]:
    """Nouvel ensemble de canaux actifs après un LinkADRReq.

    Lève ValueError si la commande est invalide ou si aucun canal ne reste actif
    (dans ce cas l'appareil doit répondre ChMaskAck = 0).
    """
    _check_family(plan_name)
    _validate_mask(ch_mask, ch_mask_cntl)
    if any(not 0 <= c < CHANNEL_COUNT for c in enabled):
        raise ValueError("ensemble de canaux hors 0..71")
    active = set(enabled)

    def set_bits(first: int, width: int) -> None:
        for bit in range(width):
            channel = first + bit
            if ch_mask >> bit & 1:
                active.add(channel)
            else:
                active.discard(channel)

    if ch_mask_cntl <= 3:
        set_bits(16 * ch_mask_cntl, 16)
    elif ch_mask_cntl == 4:
        set_bits(_FIRST_500, 8)
    elif ch_mask_cntl == 5:
        for bank in range(8):
            on = bool(ch_mask >> bank & 1)
            for channel in range(8 * bank, 8 * bank + 8):
                (active.add if on else active.discard)(channel)
            (active.add if on else active.discard)(_FIRST_500 + bank)
    elif ch_mask_cntl == 6:
        active.update(range(0, _LAST_125 + 1))
        set_bits(_FIRST_500, 8)
    else:  # 7
        active.difference_update(range(0, _LAST_125 + 1))
        set_bits(_FIRST_500, 8)

    if not active:
        raise ValueError("aucun canal actif après LinkADRReq")
    return frozenset(active)

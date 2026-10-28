"""ADR serveur : décision débit / puissance à partir de l'historique de SNR (cœur natif).

Fonction pure : aucun état conservé. Les SNR sont en dB (converties en dixièmes de dB
pour le cœur). Le modèle et ses limites sont décrits dans `core/include/lsim/adr.hpp`.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Sequence

from lsim._native import LIB, _CAdrInput, _CAdrOutput
from lsim.lora import StatusError

MAX_SAMPLES = 20
DR_COUNT = 16


@dataclass(frozen=True)
class AdrDecision:
    dr: int
    tx_power_index: int

    def changed_from(self, dr: int, tx_power_index: int) -> bool:
        return self.dr != dr or self.tx_power_index != tx_power_index


def _tenth(name: str, value: float) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} doit être un nombre")
    return int(round(value * 10))


def decide(
    snr_db: Sequence[float],
    *,
    dr: int,
    dr_sf: Sequence[int],
    min_dr: int,
    max_dr: int,
    tx_power_index: int,
    max_tx_power_index: int,
    power_step_db: float,
    installation_margin_db: float = 10.0,
) -> AdrDecision:
    """Recommande (débit, index de puissance) à partir des SNR des dernières trames.

    `dr_sf[i]` est le SF du débit i (7..12), 0 si indisponible. `power_step_db` est le pas
    d'index de puissance de la région. Lève ValueError pour une forme invalide, StatusError
    (761) si le cœur refuse une valeur hors plage.
    """
    if not 1 <= len(snr_db) <= MAX_SAMPLES:
        raise ValueError(f"snr_db doit contenir entre 1 et {MAX_SAMPLES} valeurs")
    if len(dr_sf) != DR_COUNT:
        raise ValueError(f"dr_sf doit contenir exactement {DR_COUNT} valeurs")

    c = _CAdrInput()
    for i, s in enumerate(snr_db):
        c.snr_tenth_db[i] = _tenth(f"snr_db[{i}]", s)
    c.n_samples = len(snr_db)
    for i, sf in enumerate(dr_sf):
        if isinstance(sf, bool) or not isinstance(sf, int) or not 0 <= sf <= 12:
            raise ValueError("dr_sf : valeurs entre 0 et 12")
        c.dr_sf[i] = sf
    for name, value, hi in (("dr", dr, 15), ("min_dr", min_dr, 15), ("max_dr", max_dr, 15),
                            ("tx_power_index", tx_power_index, 15),
                            ("max_tx_power_index", max_tx_power_index, 15)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= hi:
            raise ValueError(f"{name} doit être un entier entre 0 et {hi}")
    c.dr, c.min_dr, c.max_dr = dr, min_dr, max_dr
    c.tx_power_index, c.max_tx_power_index = tx_power_index, max_tx_power_index
    c.power_step_tenth_db = _tenth("power_step_db", power_step_db)
    c.installation_margin_tenth_db = _tenth("installation_margin_db", installation_margin_db)

    out = _CAdrOutput()
    status = LIB.lsim_adr_decide(ctypes.byref(c), ctypes.byref(out))
    if status != 0:
        raise StatusError(status)
    return AdrDecision(int(out.dr), int(out.tx_power_index))

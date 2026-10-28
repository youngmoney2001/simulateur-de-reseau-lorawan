"""Calibrage de la loi log-distance sur des mesures terrain.

Modèle ajusté : PL(d) = PL0 + 10 n log10(d / d0), par moindres carrés sur
x = 10 log10(d / d0) et y = perte mesurée. Les sorties sont :

- `exponent` (n) : pente, à reporter dans `propagation.exponent` ;
- `pl0_db` : perte mesurée à d0 ; `offset_db` = PL0 - FSPL(d0) (écart au modèle
  espace libre, informatif : le scénario ne le configure pas encore) ;
- `sigma_db` : écart-type des résidus (estimation du shadowing) ;
- `r2`, nombre de mesures, plage de distances, avertissements.

Format CSV attendu (en-tête obligatoire). Deux variantes :
  1) distance_m,path_loss_db
  2) distance_m,tx_power_dbm,rssi_dbm,gain_db
     où path_loss_db = tx_power_dbm + gain_db - rssi_dbm
     (gain_db = gains émission + réception - pertes de câble).

Aucune mesure n'est inventée : sans données réelles, le calibrage ne produit rien.
Ce module ne valide pas le modèle : il ajuste une pente et donne les indicateurs.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lsim.radio import free_space_path_loss_db

MIN_MEASURES = 10
MAX_MEASURES = 1_000_000
PLAUSIBLE_EXPONENT = (1.6, 4.5)  # plage usuelle en extérieur, hors avertissement


@dataclass(frozen=True)
class CalibrationReport:
    measures: int
    d0_m: float
    exponent: float
    pl0_db: float
    offset_db: Optional[float]
    sigma_db: float
    r2: float
    distance_min_m: float
    distance_max_m: float
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "measures": self.measures,
            "d0_m": self.d0_m,
            "exponent": self.exponent,
            "pl0_db": self.pl0_db,
            "offset_db": self.offset_db,
            "sigma_db": self.sigma_db,
            "r2": self.r2,
            "distance_min_m": self.distance_min_m,
            "distance_max_m": self.distance_max_m,
            "warnings": list(self.warnings),
        }


def _read_measures(path: Path) -> tuple[list[float], list[float]]:
    """Retourne (distances, pertes). Lecture stricte, erreurs avec numéro de ligne."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = set(reader.fieldnames or [])
        if "distance_m" not in fields:
            raise ValueError("calibrage : colonne 'distance_m' absente")
        use_pl = "path_loss_db" in fields
        if not use_pl and not {"tx_power_dbm", "rssi_dbm", "gain_db"} <= fields:
            raise ValueError("calibrage : colonnes 'path_loss_db' ou "
                             "'tx_power_dbm,rssi_dbm,gain_db' requises")
        distances: list[float] = []
        losses: list[float] = []
        for lineno, row in enumerate(reader, start=2):
            if len(distances) >= MAX_MEASURES:
                raise ValueError(f"calibrage : au plus {MAX_MEASURES} mesures")
            try:
                d = float(row["distance_m"])
                if use_pl:
                    pl = float(row["path_loss_db"])
                else:
                    pl = (float(row["tx_power_dbm"]) + float(row["gain_db"])
                          - float(row["rssi_dbm"]))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"calibrage ligne {lineno} : valeur non numérique") from exc
            if not (math.isfinite(d) and math.isfinite(pl)):
                raise ValueError(f"calibrage ligne {lineno} : valeur non finie")
            if d <= 0:
                raise ValueError(f"calibrage ligne {lineno} : distance strictement positive requise")
            distances.append(d)
            losses.append(pl)
    return distances, losses


def calibrate_path_loss(measures_path: str | Path, d0_m: float = 1.0,
                        frequency_hz: float = 868.1e6) -> CalibrationReport:
    """Ajuste n et PL0 sur les mesures ; refuse les jeux insuffisants."""
    if not (math.isfinite(d0_m) and d0_m > 0):
        raise ValueError("calibrage : d0 doit être strictement positif")
    path = Path(measures_path)
    distances, losses = _read_measures(path)
    n_meas = len(distances)
    if n_meas < MIN_MEASURES:
        raise ValueError(f"calibrage : au moins {MIN_MEASURES} mesures requises (reçu {n_meas})")
    if any(d < d0_m for d in distances):
        raise ValueError("calibrage : mesures plus proches que d0 ; augmenter d0 ou filtrer")

    xs = [10.0 * math.log10(d / d0_m) for d in distances]
    if len({round(x, 9) for x in xs}) < 3:
        raise ValueError("calibrage : au moins 3 distances différentes requises")
    mean_x = sum(xs) / n_meas
    mean_y = sum(losses) / n_meas
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, losses))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, losses)]
    ss_res = sum(r * r for r in residuals)
    ss_tot = sum((y - mean_y) ** 2 for y in losses)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    sigma = math.sqrt(ss_res / (n_meas - 2)) if n_meas > 2 else float("nan")

    warnings: list[str] = []
    lo, hi = PLAUSIBLE_EXPONENT
    if not lo <= slope <= hi:
        warnings.append(f"exposant {slope:.2f} hors de la plage usuelle [{lo}, {hi}] : "
                        "vérifier les unités, les gains et la distance")
    if n_meas < 30:
        warnings.append("moins de 30 mesures : incertitude élevée sur n et sigma")
    if r2 < 0.5:
        warnings.append(f"R2 = {r2:.2f} : la loi log-distance explique peu la variation")

    fspl_d0 = free_space_path_loss_db(d0_m, frequency_hz)
    return CalibrationReport(
        measures=n_meas,
        d0_m=d0_m,
        exponent=slope,
        pl0_db=intercept,
        offset_db=intercept - fspl_d0,
        sigma_db=sigma,
        r2=r2,
        distance_min_m=min(distances),
        distance_max_m=max(distances),
        warnings=tuple(warnings),
    )


def format_report(report: CalibrationReport) -> str:
    lines = [
        f"mesures : {report.measures} (d de {report.distance_min_m:.1f} à "
        f"{report.distance_max_m:.1f} m)",
        f"d0 = {report.d0_m:g} m",
        f"exposant n = {report.exponent:.3f}  ->  propagation.exponent: {report.exponent:.2f}",
        f"PL(d0) mesurée = {report.pl0_db:.2f} dB ; écart à l'espace libre = "
        f"{report.offset_db:+.2f} dB (non configurable dans le scénario)",
        f"sigma (shadowing estimé) = {report.sigma_db:.2f} dB ; R2 = {report.r2:.3f}",
    ]
    lines += [f"avertissement : {w}" for w in report.warnings]
    return "\n".join(lines)

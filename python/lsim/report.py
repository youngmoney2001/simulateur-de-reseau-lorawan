"""Rapports de simulation : feuille Excel (.xlsx) et document PDF.

Les chiffres viennent du résultat natif (`RunResult`) ; ce module ne calcule que les
taux d'affichage. Les textes issus du scénario (nom, groupes) sont neutralisés contre
l'injection de formules tableur (`=`, `+`, `-`, `@` en tête de cellule).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional, Sequence, Union

from lsim import __version__
from lsim.energy_report import DeviceEnergy, profile_name
from lsim.export import RunResult

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_text(value: str) -> str:
    """Neutralise une chaîne pouvant être interprétée comme formule tableur."""
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _energy_index(energy: Optional[Sequence[DeviceEnergy]]) -> Mapping[int, DeviceEnergy]:
    return {e.device_index: e for e in energy} if energy is not None else {}


def _fmt_mj(value: Optional[float]) -> object:
    return round(value * 1e3, 6) if value is not None else "n/a"


def _summary_rows(result: RunResult, energy_profile: Optional[str] = None
                  ) -> list[tuple[str, object]]:
    t = result.totals
    g = result.gateway
    pdr = f"{result.pdr * 100:.2f} %" if result.pdr is not None else "n/a"
    energy_rows = [("Profil énergie (classe A, un message par période)",
                    profile_name(energy_profile))] if energy_profile is not None else []
    return [
        ("Scénario", _safe_text(result.scenario_name)),
        ("Empreinte SHA-256 du scénario", result.scenario_sha256),
        ("Graine", result.seed),
        ("Version lsim (Python)", __version__),
        ("Émises", t.sent),
        ("Reçues", t.received),
        ("PDR", pdr),
        ("Pertes par sensibilité", t.lost_sensitivity),
        ("Pertes par collision", t.lost_collision),
        ("Temps d'antenne total (ns)", t.airtime_ns),
        ("Charge passerelle : durée occupée (ns)", g.busy_ns),
        ("Charge passerelle : pic de trames simultanées", g.peak_concurrent),
        ("Charge passerelle : taux d'occupation", round(g.utilization, 6)),
    ] + energy_rows


def write_xlsx(result: RunResult, path: Union[str, Path], *,
               energy_profile: Optional[str] = None,
               energy: Optional[Sequence[DeviceEnergy]] = None) -> None:
    """Écrit un classeur : « Synthèse » et « Dispositifs » (une ligne par dispositif).

    `energy_profile` et `energy` (sortie de `energy_report.device_energies`) ajoutent
    l'énergie par message et le courant moyen.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse"
    ws.append(["Indicateur", "Valeur"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for label, value in _summary_rows(result, energy_profile):
        ws.append([label, value])
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 66

    dv = wb.create_sheet("Dispositifs")
    headers = ["Index", "Groupe", "Index dans le groupe", "x (m)", "y (m)", "SF",
               "Émises", "Reçues", "Pertes sensibilité", "Pertes collision", "PDR",
               "Temps d'antenne (ns)"]
    with_energy = energy is not None
    if with_energy:
        headers += ["Énergie par message (mJ)", "Courant moyen (µA)"]
    emap = _energy_index(energy)
    dv.append(headers)
    for c in dv[1]:
        c.font = Font(bold=True)
    for r in result.rows:
        line = [
            r.device_index, _safe_text(r.group), r.index_in_group, r.x_m, r.y_m,
            r.spreading_factor, r.sent, r.received, r.lost_sensitivity, r.lost_collision,
            r.pdr if r.pdr is not None else "", r.airtime_ns,
        ]
        if with_energy:
            e = emap.get(r.device_index)
            line += [_fmt_mj(e.energy_per_message_j) if e else "n/a",
                     round(e.average_current_ua, 6) if e and e.average_current_ua is not None
                     else "n/a"]
        dv.append(line)
    dv.freeze_panes = "A2"
    dv.auto_filter.ref = dv.dimensions
    wb.save(path)


def write_pdf(result: RunResult, path: Union[str, Path], *,
              energy_profile: Optional[str] = None,
              energy: Optional[Sequence[DeviceEnergy]] = None) -> None:
    """Écrit un rapport PDF : synthèse et tableau des 200 premiers dispositifs.

    Avec `energy`, le tableau ajoute l'énergie par message (mJ) et le courant moyen (µA).
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    story = [Paragraph("Rapport de simulation LoRaWAN", styles["Title"]), Spacer(1, 12)]
    summary = [[Paragraph(escape(str(k)), styles["Normal"]), Paragraph(escape(str(v)), styles["Normal"])]
               for k, v in _summary_rows(result, energy_profile)]
    t = Table(summary, colWidths=[210, 290])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 18)]

    shown = result.rows[:200]
    story.append(Paragraph(f"Dispositifs ({len(shown)} sur {len(result.rows)} affichés)",
                           styles["Heading2"]))
    with_energy = energy is not None
    emap = _energy_index(energy)
    rows = [["Index", "Groupe", "SF", "Émises", "Reçues", "PDR"]]
    if with_energy:
        rows[0] += ["mJ/msg", "µA moy."]
    for r in shown:
        line = [str(r.device_index), escape(r.group)[:24], str(r.spreading_factor),
                str(r.sent), str(r.received),
                f"{r.pdr * 100:.1f} %" if r.pdr is not None else "n/a"]
        if with_energy:
            e = emap.get(r.device_index)
            line += [f"{e.energy_per_message_j * 1e3:.3f}"
                     if e and e.energy_per_message_j is not None else "n/a",
                     f"{e.average_current_ua:.3f}"
                     if e and e.average_current_ua is not None else "n/a"]
        rows.append(line)
    dt = Table(rows, repeatRows=1)
    dt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    story.append(dt)

    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Rapport de simulation LoRaWAN")
    doc.build(story)

"""Rapports de simulation : feuille Excel (.xlsx) et document PDF.

Les chiffres viennent du résultat natif (`RunResult`) ; ce module ne calcule que les
taux d'affichage. Les textes issus du scénario (nom, groupes) sont neutralisés contre
l'injection de formules tableur (`=`, `+`, `-`, `@` en tête de cellule).
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from lsim import __version__
from lsim.export import RunResult

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_text(value: str) -> str:
    """Neutralise une chaîne pouvant être interprétée comme formule tableur."""
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _summary_rows(result: RunResult) -> list[tuple[str, object]]:
    t = result.totals
    g = result.gateway
    pdr = f"{result.pdr * 100:.2f} %" if result.pdr is not None else "n/a"
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
    ]


def write_xlsx(result: RunResult, path: Union[str, Path]) -> None:
    """Écrit un classeur : « Synthèse » et « Dispositifs » (une ligne par dispositif)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse"
    ws.append(["Indicateur", "Valeur"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for label, value in _summary_rows(result):
        ws.append([label, value])
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 66

    dv = wb.create_sheet("Dispositifs")
    headers = ["Index", "Groupe", "Index dans le groupe", "x (m)", "y (m)", "SF",
               "Émises", "Reçues", "Pertes sensibilité", "Pertes collision", "PDR",
               "Temps d'antenne (ns)"]
    dv.append(headers)
    for c in dv[1]:
        c.font = Font(bold=True)
    for r in result.rows:
        dv.append([
            r.device_index, _safe_text(r.group), r.index_in_group, r.x_m, r.y_m,
            r.spreading_factor, r.sent, r.received, r.lost_sensitivity, r.lost_collision,
            r.pdr if r.pdr is not None else "", r.airtime_ns,
        ])
    dv.freeze_panes = "A2"
    dv.auto_filter.ref = dv.dimensions
    wb.save(path)


def write_pdf(result: RunResult, path: Union[str, Path]) -> None:
    """Écrit un rapport PDF : synthèse et tableau des 200 premiers dispositifs."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    story = [Paragraph("Rapport de simulation LoRaWAN", styles["Title"]), Spacer(1, 12)]
    summary = [[Paragraph(escape(str(k)), styles["Normal"]), Paragraph(escape(str(v)), styles["Normal"])]
               for k, v in _summary_rows(result)]
    t = Table(summary, colWidths=[210, 290])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 18)]

    shown = result.rows[:200]
    story.append(Paragraph(f"Dispositifs ({len(shown)} sur {len(result.rows)} affichés)",
                           styles["Heading2"]))
    rows = [["Index", "Groupe", "SF", "Émises", "Reçues", "PDR"]]
    for r in shown:
        rows.append([str(r.device_index), escape(r.group)[:24], str(r.spreading_factor),
                     str(r.sent), str(r.received),
                     f"{r.pdr * 100:.1f} %" if r.pdr is not None else "n/a"])
    dt = Table(rows, repeatRows=1)
    dt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    story.append(dt)

    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Rapport de simulation LoRaWAN")
    doc.build(story)

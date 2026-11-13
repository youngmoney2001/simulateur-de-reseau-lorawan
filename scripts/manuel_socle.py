"""Socle des manuels PDF : styles, blocs, et lecture des grandeurs dans le moteur.

Deux idées tiennent tout ce socle :

1. **Aucune valeur numérique n'est recopiée.** Elle est lue dans `liblsim_core` au moment où
   le manuel est généré. Un manuel qui recopie une constante cesse de valoir le jour où le
   moteur en change, sans que rien ne le signale ; un manuel qui la lit ne peut pas mentir.
   C'est la même règle que celle de l'atelier, où les libellés et les listes viennent du
   serveur.

2. **Aucun texte n'est injecté.** Tout passe par `escape`, comme dans `lsim.report` : un
   libellé de scénario est une donnée, pas une mise en page.

Les manuels sont générés (et non écrits à la main) pour cette seule raison : ce qui est
mesuré se vérifie à chaque génération, ce qui est écrit à la main dérive sans bruit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

# --- Lecture des grandeurs dans le moteur -------------------------------------------------------


def version() -> str:
    import lsim
    return getattr(lsim, "__version__", "inconnue")


def sensibilites() -> list[tuple[int, float, float, float]]:
    """Sensibilité (dBm) par SF, pour les trois bandes. Table lue dans le cœur natif."""
    from lsim import radio
    rows = []
    for sf in range(7, 13):
        vals = [radio.receiver_sensitivity_dbm(sf, bw) for bw in (125_000, 250_000, 500_000)]
        rows.append((sf, *vals))
    return rows


def airtimes(payload_bytes: int = 10, bandwidth_hz: int = 125_000) -> list[tuple[int, float]]:
    """Temps d'antenne (ms) par SF, pour une charge donnée."""
    from lsim.lora import RadioConfig, time_on_air_ns
    return [(sf, time_on_air_ns(RadioConfig(spreading_factor=sf, bandwidth_hz=bandwidth_hz),
                                payload_bytes) / 1e6)
            for sf in range(7, 13)]


def pertes_log_distance(distances=(100, 1000, 3000, 10000)) -> list[tuple[int, float]]:
    """Perte log-distance (dB) aux distances données, dans la configuration de référence."""
    from lsim import radio
    m = radio.LogDistanceModel(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=2.7)
    return [(d, m.path_loss_db(d)) for d in distances]


def perte_espace_libre(distance_m: float = 1000.0, frequency_hz: float = 868.1e6) -> float:
    from lsim import radio
    return radio.free_space_path_loss_db(distance_m, frequency_hz)


def profils_energie() -> list[dict]:
    """Les deux profils de matériel, tels que le moteur les déclare."""
    from lsim.energy import profile
    from lsim.energy_report import ENERGY_PROFILES, PROFILE_NAMES
    out = []
    for nom in sorted(ENERGY_PROFILES):
        p = profile(ENERGY_PROFILES[nom])
        out.append({"nom": nom, "libelle": PROFILE_NAMES[ENERGY_PROFILES[nom]],
                    "tension_v": p.supply_v, "rx_ma": p.rx_ma_125khz, "veille_ua": p.sleep_ua,
                    "mcu_run_ma": p.mcu_run_ma})
    return out


def defaut_energie() -> str:
    from lsim.energy_report import DEFAULT_ENERGY_PROFILE
    return DEFAULT_ENERGY_PROFILE


def configuration_radio() -> dict:
    """La configuration radio par défaut du moteur (celle des tables de ce manuel)."""
    from lsim.lora import RadioConfig
    c = RadioConfig()
    return {"sf": c.spreading_factor, "bw_hz": c.bandwidth_hz, "cr": c.coding_rate,
            "preambule": c.preamble_symbols, "crc": c.crc_on, "entete_explicite": c.explicit_header,
            "ldro": c.low_data_rate_optimize}


def bornes_propagation() -> dict:
    """Défauts et bornes du modèle de propagation, lus dans le contrat de scénario."""
    from lsim.scenario import PropagationModel
    f = PropagationModel.model_fields
    return {"frequence_hz": f["frequency_hz"].default,
            "d0_m": f["reference_distance_m"].default,
            "exposant": f["exponent"].default,
            "exposant_min": 1.0, "exposant_max": 6.0,
            "capture_db": f["capture_threshold_db"].default,
            "shadowing_sigma": f["shadowing_sigma_db"].default,
            "shadowing_max": 30.0}


def aide_cli(sous_commande: str = "") -> str:
    """L'aide réelle de la ligne de commande, lue à l'exécution.

    Une commande documentée à la main dérive dès que son options changent, et rien ne le
    signale. Celle-ci ne peut pas être en retard : elle est ce que l'utilisateur obtient en
    tapant la commande.
    """
    import subprocess
    import sys
    args = [sys.executable, "-m", "lsim"] + ([sous_commande] if sous_commande else []) + ["--help"]
    out = subprocess.run(args, capture_output=True, text=True)
    return (out.stdout or out.stderr).rstrip()


def champs(modele) -> list[tuple[str, str, str]]:
    """(nom, type lisible, défaut) de chaque champ d'un modèle Pydantic du contrat."""
    rows = []
    for nom, f in modele.model_fields.items():
        t = str(f.annotation)
        for bruit in ("typing.", "lsim.scenario.", "lsim.study_contract.", "<class '", "'>"):
            t = t.replace(bruit, "")
        d = f.default
        if f.is_required():
            # Aucun défaut : le champ doit être écrit. « Optional » veut dire qu'il peut
            # valoir null, pas qu'on peut l'omettre — confondre les deux ferait croire
            # obligatoire un champ qu'on a parfaitement le droit de ne pas écrire.
            defaut = "obligatoire"
        elif d is None:
            defaut = "absent (facultatif)"
        elif hasattr(d, "model_dump"):
            defaut = "objet (voir ci-dessous)"
        else:
            defaut = repr(d)
        rows.append((nom, t[:60], defaut[:40]))
    return rows


def regions() -> list[dict]:
    """Les plans régionaux, tels que le moteur les publie."""
    from lsim.api_contract import list_regions
    out = []
    for r in list_regions().regions:
        out.append({"nom": r.name, "canaux": len(r.uplink_channels_hz),
                    "rx2_hz": r.rx2_hz, "rx2_datr": r.rx2_datr,
                    "sous_bandes": r.sub_bands})
    return out


def exercices() -> list[dict]:
    """Le catalogue d'exercices notés de l'atelier, tel que le serveur le publie."""
    from lsim.study_exercises import listing
    return [{"id": e.id, "titre": e.title, "points": e.max_points,
             "indices": e.hints_available} for e in listing().items]


# --- Mise en page ------------------------------------------------------------------------------

_STYLES = getSampleStyleSheet()

TITRE = ParagraphStyle("mtitre", parent=_STYLES["Title"], fontSize=22, leading=27, spaceAfter=4)
SOUS_TITRE = ParagraphStyle("msoustitre", parent=_STYLES["Normal"], fontSize=12, leading=16,
                            alignment=1, textColor=colors.HexColor("#444444"), spaceAfter=18)
H1 = ParagraphStyle("mh1", parent=_STYLES["Heading1"], fontSize=15, leading=19, spaceBefore=16,
                    spaceAfter=7, textColor=colors.HexColor("#12324f"))
H2 = ParagraphStyle("mh2", parent=_STYLES["Heading2"], fontSize=11.5, leading=15, spaceBefore=11,
                    spaceAfter=5, textColor=colors.HexColor("#1d4e73"))
CORPS = ParagraphStyle("mcorps", parent=_STYLES["Normal"], fontSize=9.5, leading=13.5,
                       alignment=TA_JUSTIFY, spaceAfter=6)
NOTE = ParagraphStyle("mnote", parent=CORPS, fontSize=8.5, leading=12,
                      textColor=colors.HexColor("#555555"), leftIndent=8)
FORMULE = ParagraphStyle("mformule", parent=_STYLES["Normal"], fontName="Courier", fontSize=8.5,
                         leading=12.5, leftIndent=14, spaceBefore=4, spaceAfter=6,
                         textColor=colors.HexColor("#1a1a1a"))
LEGENDE = ParagraphStyle("mlegende", parent=_STYLES["Normal"], fontSize=8, leading=11,
                         textColor=colors.HexColor("#666666"), spaceAfter=10)
CELLULE = ParagraphStyle("mcellule", parent=_STYLES["Normal"], fontSize=8, leading=11)
CELLULE_TETE = ParagraphStyle("mcellule_tete", parent=CELLULE, fontName="Helvetica-Bold")


def p(texte: str, style=CORPS):
    return Paragraph(escape(texte), style)


def brut(texte: str, style=CORPS):
    """Texte déjà balisé : réservé aux rares cas où l'on veut du gras ou de l'italique."""
    return Paragraph(texte, style)


def formule(texte: str):
    return Paragraph(escape(texte).replace("\n", "<br/>"), FORMULE)


def titre(texte: str):
    return Paragraph(escape(texte), TITRE)


def sous_titre(texte: str):
    return Paragraph(escape(texte), SOUS_TITRE)


def tableau(entetes: list[str], lignes: list[list[str]], largeurs=None, note: str = ""):
    """Un tableau de texte, avec en-tête répétée en haut de chaque page."""
    data = [[Paragraph(escape(h), CELLULE_TETE) for h in entetes]]
    for ligne in lignes:
        data.append([Paragraph(escape(str(c)), CELLULE) for c in ligne])
    t = Table(data, colWidths=largeurs, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    if not note:
        return t
    return [t, Spacer(1, 3), Paragraph(escape(note), LEGENDE)]


def bloc_garde(titre_doc: str, sous: str, mention: str) -> list:
    """Page de garde commune aux deux manuels."""
    return [
        Spacer(1, 55 * mm),
        titre(titre_doc),
        sous_titre(sous),
        Spacer(1, 12 * mm),
        p(mention, NOTE),
        Spacer(1, 6 * mm),
        p(f"Version du moteur : {version()} — généré le "
          f"{datetime.now(timezone.utc).strftime('%d/%m/%Y')} (UTC)", NOTE),
        PageBreak(),
    ]


def aplatir(elements) -> list:
    """Déplie la story : `tableau` rend une liste quand il porte une note, et une section
    concatène des listes. Reportlab veut une suite plate de blocs."""
    plats = []
    for e in elements:
        if isinstance(e, (list, tuple)):
            plats.extend(aplatir(e))
        else:
            plats.append(e)
    return plats


def _sans_balises(texte: str) -> str:
    """Le texte d'un paragraphe, sans le balisage reportlab.

    getPlainText() ôte les balises mais avale aussi les <br/> : deux lignes de commande
    se retrouvent collées, et le miroir cesse de ressembler au PDF. On garde donc les
    retours à la ligne, et on déjoue l'échappement appliqué à la génération.
    """
    import html
    import re
    t = re.sub(r"(?i)<br\s*/?>", "\n", texte)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t).strip()


def texte_de(story) -> str:
    """Le texte de la story, bloc par bloc.

    Il sert de miroir lisible : un PDF ne se relit pas d'un coup d'œil, ne se compare pas
    d'une génération à l'autre, et n'entre pas dans un test. Ce fichier texte, si. C'est ce
    qui permet de vérifier qu'une valeur attendue est bien présente, sans ouvrir le PDF.
    """
    out = []
    for f in story:
        if isinstance(f, Paragraph):
            out.append(_sans_balises(f.text))
        elif isinstance(f, Table):
            for ligne in f._cellvalues:
                cellules = [_sans_balises(c.text) if isinstance(c, Paragraph) else str(c)
                            for c in ligne]
                out.append(" | ".join(cellules))
    return "\n".join(out) + "\n"


def ecrire(nom_fichier: str, story: list, titre_doc: str, miroir: bool = True) -> None:
    """Construit le PDF. Pied de page avec folio et titre du document."""
    story = aplatir(story)
    if miroir:
        with open(str(nom_fichier).replace(".pdf", ".txt"), "w", encoding="utf-8") as fh:
            fh.write(texte_de(story))
    doc = BaseDocTemplate(nom_fichier, pagesize=A4, leftMargin=22 * mm, rightMargin=18 * mm,
                          topMargin=20 * mm, bottomMargin=18 * mm,
                          title=titre_doc, author="lsim")
    cadre = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="cadre")

    def pied(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(doc_.leftMargin, 11 * mm, escape(titre_doc))
        canvas.drawRightString(A4[0] - doc_.rightMargin, 11 * mm, f"page {doc_.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="toutes", frames=[cadre], onPage=pied)])
    doc.build(story)

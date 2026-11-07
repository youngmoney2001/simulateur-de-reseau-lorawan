"""Service des fichiers du studio web precompile (distribution sans Node).

Le studio est une application Vite : `npm run build` produit un dossier de fichiers statiques
(`studio.html`, `index.html`, `assets/...`). Servi par le serveur Python, il n y a plus besoin de
Node ni de Vite a l execution : un seul processus suffit, sur un seul port.

La recherche du dossier suit cet ordre : 1) chemin explicite (--dist), 2) variable
LSIM_STUDIO_DIST, 3) `web_dist` a cote de ce module (installation empquetee), 4) `web/dist` a la
racine du depot (developpement depuis les sources).

La resolution refuse toute traversee : un chemin qui sort de la racine est rejete.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["TYPES_MIME", "content_type", "find_dist", "resolve_asset"]

TYPES_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".woff2": "font/woff2",
    ".wasm": "application/wasm",
    ".ico": "image/x-icon",
}


def find_dist(explicit=None):
    """Dossier du studio precompile ; None si la decouverte n en trouve aucun.

    Un chemin impose (`explicit` ou `LSIM_STUDIO_DIST`) est **autoritaire** : il vient d une
    demande de l utilisateur, on le sert ou on echoue. Jamais on ne lui substitue en silence un
    autre dossier (arbitrage bbb3) : servir un studio que l utilisateur n a pas demande est
    pire que ne rien servir, car le defaut passe inapercu.

    Sans chemin impose, la decouverte est tolerante : le serveur doit pouvoir demarrer sans
    studio, en le signalant.
    """
    impose = explicit or os.environ.get("LSIM_STUDIO_DIST")
    if impose:
        cible = Path(impose)
        if not (cible / "studio.html").is_file():
            raise ValueError(
                f"studio introuvable dans {cible} : aucun fichier studio.html. "
                f"Compiler le studio (scripts/package_studio.sh) ou corriger le chemin.")
        return cible.resolve()
    ici = Path(__file__).resolve().parent
    for c in (ici / "web_dist", ici.parent.parent / "web" / "dist"):
        try:
            if (c / "studio.html").is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def content_type(path):
    """Type MIME d apres l extension ; defaut binaire."""
    return TYPES_MIME.get(path.suffix.lower(), "application/octet-stream")


def resolve_asset(root, url_path):
    """Chemin sur sous `root`, ou None : refuse toute sortie de la racine.

    Trois refus, explicites et silencieux : element `..`, chemin resolu hors de `root`,
    fichier inexistant. Un chemin refuse n est jamais servi.
    """
    rel = url_path.split("?", 1)[0].split("#", 1)[0].strip("/")
    if not rel or rel.endswith("/"):
        rel = (rel + "index.html").lstrip("/")
    if ".." in Path(rel).parts:
        return None
    cible = (root / rel).resolve()
    racine = root.resolve()
    if cible != racine and not str(cible).startswith(str(racine) + os.sep):
        return None
    return cible if cible.is_file() else None

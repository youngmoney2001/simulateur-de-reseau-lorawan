"""Tests du service des fichiers du studio precompile.

Le point sensible est la traversee de repertoire : ces tests verifient qu aucun chemin ne permet
de sortir de la racine servie.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lsim.studio_static import content_type, find_dist, resolve_asset


class Service(unittest.TestCase):
    """Une racine temporaire avec quelques fichiers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name) / "dist"
        (self.racine / "assets").mkdir(parents=True)
        (self.racine / "studio.html").write_text("<html>", encoding="utf-8")
        (self.racine / "index.html").write_text("<html>", encoding="utf-8")
        (self.racine / "assets" / "a.js").write_text("1", encoding="utf-8")
        (self.racine.parent / "secret.txt").write_text("secret", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_racine_servie_index(self):
        self.assertEqual(resolve_asset(self.racine, "/"), self.racine / "index.html")

    def test_fichier_nomme_servi(self):
        self.assertEqual(resolve_asset(self.racine, "/studio.html"), self.racine / "studio.html")

    def test_sous_dossier_servi(self):
        self.assertEqual(resolve_asset(self.racine, "/assets/a.js"),
                         self.racine / "assets" / "a.js")

    def test_traversee_simple_refusee(self):
        self.assertIsNone(resolve_asset(self.racine, "/../secret.txt"))

    def test_traversee_double_slash_refusee(self):
        self.assertIsNone(resolve_asset(self.racine, "//etc/passwd"))

    def test_traversee_imbriquee_refusee(self):
        self.assertIsNone(resolve_asset(self.racine, "/assets/../../secret.txt"))

    def test_chemin_absolu_refuse(self):
        self.assertIsNone(resolve_asset(self.racine, "/etc/passwd"))

    def test_fichier_absent_refuse(self):
        self.assertIsNone(resolve_asset(self.racine, "/inexistant.js"))


class Recherche(unittest.TestCase):
    """Un chemin demande est autoritaire ; la decouverte seule est tolerante."""

    def test_chemin_impose_sans_studio_echoue(self):
        """Un chemin demande est servi ou refuse, jamais remplace en silence (bbb3)."""
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                find_dist(d)

    def test_le_message_nomme_le_chemin_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as ctx:
                find_dist(d)
        self.assertIn(str(Path(d)), str(ctx.exception))

    def test_chemin_impose_avec_studio(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "studio.html").write_text("<html>", encoding="utf-8")
            self.assertEqual(find_dist(d), Path(d).resolve())

    def test_decouverte_rend_un_studio_ou_rien(self):
        """Sans chemin impose, la decouverte ne leve pas : elle rend un dossier qui porte
        reellement le studio, ou None. Jamais un dossier sans studio.html."""
        d = find_dist()
        if d is not None:
            self.assertTrue((d / "studio.html").is_file())


class Types(unittest.TestCase):

    def test_html(self):
        self.assertIn("text/html", content_type(Path("a.html")))

    def test_js(self):
        self.assertIn("javascript", content_type(Path("a.js")))

    def test_inconnu_est_binaire(self):
        self.assertEqual(content_type(Path("a.bin")), "application/octet-stream")

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

    def test_chemin_explicite_sans_studio_est_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(find_dist(d))

    def test_chemin_explicite_avec_studio(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "studio.html").write_text("<html>", encoding="utf-8")
            self.assertEqual(find_dist(d), Path(d).resolve())


class Types(unittest.TestCase):

    def test_html(self):
        self.assertIn("text/html", content_type(Path("a.html")))

    def test_js(self):
        self.assertIn("javascript", content_type(Path("a.js")))

    def test_inconnu_est_binaire(self):
        self.assertEqual(content_type(Path("a.bin")), "application/octet-stream")

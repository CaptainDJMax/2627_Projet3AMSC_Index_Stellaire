"""Partie 10 : le contenu partagé (contenu/astres/*.json et contenu/images_sources.json).

Ces tests protègent le travail à plusieurs : une fiche mal remplie (source manquante, licence
oubliée, coordonnées fausses) est vue avant le commit, pas sur le téléphone.

    python manage.py test ciel
"""

import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from . import astro
from .management.commands import telecharger_images
from .models import ObjetCeleste

CONTENU = Path(settings.BASE_DIR) / "contenu"
PARIS = (48.8566, 2.3522, 35)


def fiches():
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted((CONTENU / "astres").glob("*.json"))}


def liste_images():
    return json.loads((CONTENU / "images_sources.json").read_text(encoding="utf-8"))["images"]


class FichesTests(SimpleTestCase):
    def test_chaque_fiche_est_remplie_et_sourcee(self):
        categories = {v for v, _ in ObjetCeleste.Categorie.choices}
        for nom, d in fiches().items():
            with self.subTest(fiche=nom):
                self.assertIn(d["categorie"], categories)
                self.assertGreaterEqual(len(d["description"]), 150, "description trop courte")
                self.assertTrue(d["sources"], "au moins une source")
                self.assertTrue(all(s.startswith("https://") for s in d["sources"]))

    def test_images_avec_credit_et_dans_la_liste(self):
        images = liste_images()
        utilisees = set()
        for nom, d in fiches().items():
            if not d["image"]:
                continue
            utilisees.add(d["image"])
            with self.subTest(fiche=nom):
                self.assertIn(d["image"], images, "image absente de images_sources.json")
                self.assertTrue(d["image_auteur"] and d["image_licence"])
                self.assertEqual(d["image_source"], images[d["image"]]["page"])  # la page où le crédit a été vérifié
                self.assertTrue(images[d["image"]]["url"].startswith("https://"))
        self.assertEqual(set(images), utilisees)  # pas d'image téléchargée pour rien

    def test_positions_calculables_et_coordonnees_justes(self):
        """Chaque astre est calculable ; un point du ciel est dans la bonne constellation (contrôle des coordonnées)."""
        attendu = {"Pléiades": "Tau", "Galaxie d'Andromède": "And", "Nébuleuse d'Orion": "Ori"}
        for nom, d in fiches().items():
            with self.subTest(fiche=nom):
                if d["identifiant_skyfield"].startswith("sat:"):
                    continue  # TLE : testé dans test_satellites
                elevation, azimut = astro.altaz(d["identifiant_skyfield"], *PARIS)
                self.assertTrue(-90 <= elevation <= 90 and 0 <= azimut < 360)
                if d["nom"] in attendu:
                    infos = astro.infos(d["identifiant_skyfield"], *PARIS)
                    self.assertEqual(infos["constellation_iau"], attendu[d["nom"]])
                    self.assertIsNone(infos["distance_km"])  # pas de distance absurde pour un point du ciel

    def test_soleil(self):
        d = fiches()["soleil.json"]
        self.assertEqual((d["categorie"], d["identifiant_skyfield"]), ("soleil", "sun"))
        self.assertIn("ISO 12312-2", d["description"])  # la consigne de sécurité est dans la fiche
        i = astro.infos("sun", *PARIS)
        self.assertTrue(1.47e8 < i["distance_km"] < 1.53e8)
        self.assertIsNone(i["magnitude"])


class TelechargementTests(SimpleTestCase):
    def test_reduction(self):
        source = io.BytesIO()
        Image.new("RGBA", (3000, 2000), (200, 120, 40, 255)).save(source, "PNG")
        octets = telecharger_images.reduire(source.getvalue())
        with Image.open(io.BytesIO(octets)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (1200, 800))


class ChaineCompleteTests(TestCase):
    """telecharger_images (réseau simulé), puis importer_contenu : tout le contenu entre dans la base."""

    def test_telecharger_puis_importer(self):
        with tempfile.TemporaryDirectory() as tmp:
            dossier = Path(tmp) / "contenu"
            shutil.copytree(CONTENU, dossier, ignore=shutil.ignore_patterns("images"))
            image = io.BytesIO()
            Image.new("RGB", (1600, 1600), (10, 10, 30)).save(image, "JPEG")
            with patch("ciel.management.commands.telecharger_images.telecharger", return_value=image.getvalue()), \
                    override_settings(MEDIA_ROOT=str(Path(tmp) / "media")):
                call_command("telecharger_images", dossier=str(dossier), stdout=io.StringIO())
                call_command("importer_contenu", dossier=str(dossier), stdout=io.StringIO())
            self.assertEqual(len(list((dossier / "images").glob("*.jpg"))), len(liste_images()))
        self.assertEqual(ObjetCeleste.objects.count(), len(fiches()))
        soleil = ObjetCeleste.objects.get(nom="Soleil")
        self.assertEqual(soleil.categorie, "soleil")
        self.assertTrue(soleil.image.name.endswith("soleil.jpg"))
        self.assertIn("science.nasa.gov", soleil.sources)

    def test_fiche_du_soleil_dans_l_api(self):
        soleil = ObjetCeleste.objects.create(nom="Soleil", categorie="soleil", identifiant_skyfield="sun")
        d = self.client.get(f"/api/ciel/objets/{soleil.id}/", {"instant": "2026-06-21T12:00:00Z"}).json()
        self.assertEqual(d["categorie"], "soleil")
        self.assertGreater(d["position"]["elevation"], 60)  # midi au solstice d'été à Paris
        # Pas d'accès à internet dans les tests (règle 11) : sources externes et TLE simulés en panne
        with tempfile.TemporaryDirectory() as tmp, override_settings(DOSSIER_SOURCES_EXTERNES=tmp, DOSSIER_TLE=tmp), \
                patch("ciel.sources_externes._telecharger", side_effect=OSError("hors ligne")), \
                patch("ciel.satellites._telecharger", side_effect=OSError("hors ligne")):
            soir = self.client.get("/api/ciel/evenements/", {"instant": "2026-06-21T12:00:00Z", "jours": 1}).json()["ce_soir"]
        self.assertNotIn("Soleil", [a["nom"] for a in soir["astres"]])  # « ce soir » : Lune et planètes seulement

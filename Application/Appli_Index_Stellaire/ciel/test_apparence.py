"""Partie 10 bis : apparence des astres étendus (Soleil, Lune, amas, ciel profond) dans l'API.

    python manage.py test ciel.test_apparence
"""

from datetime import datetime, timezone

from django.test import TestCase
from skyfield.trigonometry import position_angle_of

from . import astro
from .apparence import FORMES, angle_de_position
from .models import ObjetCeleste

# Pleine Lune de l'éclipse du 28 août 2026 (vers 4 h 13 UTC)
PLEINE_LUNE = "2026-08-28T04:13:00Z"


class ApparenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ObjetCeleste.objects.create(nom="Soleil", categorie="soleil", identifiant_skyfield="sun")
        ObjetCeleste.objects.create(nom="Lune", categorie="lune", identifiant_skyfield="moon")
        ObjetCeleste.objects.create(nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter")
        ObjetCeleste.objects.create(nom="Pléiades", categorie="amas", identifiant_skyfield="radec:56.85,24.1167")
        ObjetCeleste.objects.create(
            nom="Galaxie d'Andromède", categorie="ciel_profond", identifiant_skyfield="radec:10.6846,41.2692"
        )
        ObjetCeleste.objects.create(nom="Galaxie inconnue", categorie="ciel_profond", identifiant_skyfield="radec:200,10")

    def objets(self, instant=PLEINE_LUNE):
        reponse = self.client.get("/api/ciel/objets/", {"instant": instant})
        self.assertEqual(reponse.status_code, 200)
        return {o["nom"]: o for o in reponse.json()["objets"]}

    def test_planete_sans_apparence(self):
        self.assertNotIn("apparence", self.objets()["Jupiter"])

    def test_soleil_et_lune_a_leur_vraie_taille(self):
        o = self.objets()
        self.assertEqual(o["Soleil"]["apparence"]["type"], "soleil")
        self.assertAlmostEqual(o["Soleil"]["apparence"]["diametre"], 0.53, delta=0.02)
        lune = o["Lune"]["apparence"]
        self.assertEqual({"type", "diametre", "eclairement", "angle_soleil"}, set(lune))
        self.assertTrue(0.48 <= lune["diametre"] <= 0.58)
        self.assertGreater(lune["eclairement"], 0.98)  # pleine Lune
        self.assertTrue(0 <= lune["angle_soleil"] < 360)

    def test_cote_eclaire_de_la_lune(self):
        """L'angle de position est celui de Skyfield (direction du Soleil vue de la Lune)."""
        lieu = {"latitude": 48.85, "longitude": 2.35, "altitude_m": 35}
        t = astro.instant_depuis(datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc))  # croissant du soir
        ra, dec = astro.radec("moon", lieu["latitude"], lieu["longitude"], lieu["altitude_m"], t)
        ra_s, dec_s = astro.radec("sun", lieu["latitude"], lieu["longitude"], lieu["altitude_m"], t)
        terre = astro._ephemerides()["earth"]
        lune = terre.at(t).observe(astro._ephemerides()["moon"])
        soleil = terre.at(t).observe(astro._ephemerides()["sun"])
        reference = position_angle_of(lune.radec(), soleil.radec()).degrees
        ecart = abs((angle_de_position(ra, dec, ra_s, dec_s) - reference + 180) % 360 - 180)
        self.assertLess(ecart, 1.0)
        # Croissant du soir : le Soleil est à l'ouest de la Lune (angle entre 180° et 360°)
        self.assertTrue(180 < angle_de_position(ra, dec, ra_s, dec_s) < 360)

    def test_ciel_profond_et_amas(self):
        o = self.objets()
        self.assertEqual(o["Pléiades"]["apparence"], FORMES["Pléiades"])
        self.assertEqual(o["Galaxie d'Andromède"]["apparence"], FORMES["Galaxie d'Andromède"])
        defaut = o["Galaxie inconnue"]["apparence"]
        self.assertEqual(defaut["type"], "ellipse")
        self.assertEqual({"type", "grand_axe", "petit_axe", "angle", "teinte"}, set(defaut))

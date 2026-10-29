"""Partie 8.1 : la fiche complétée (magnitude, coordonnées, constellation, distance, ce soir).

Valeurs de référence : catalogue Hipparcos (Bételgeuse : magnitude 0,45, parallaxe 7,63 mas,
dans Orion), constellations officielles de l'UAI.

    python manage.py test ciel
"""

from datetime import datetime, timezone

from django.test import TestCase

from . import astro
from .models import ObjetCeleste

PARIS = (48.8566, 2.3522, 35)


def instant(*args):
    return astro.instant_depuis(datetime(*args, tzinfo=timezone.utc))


class InfosTests(TestCase):
    def test_etoile(self):
        i = astro.infos("hip:27989", *PARIS, instant(2026, 10, 29))
        self.assertEqual(i["magnitude"], 0.45)
        self.assertEqual(i["constellation_iau"], "Ori")
        self.assertAlmostEqual(i["distance_al"], 1000 / 7.63 * astro.PARSEC_AL, delta=0.1)  # 427 a.l.
        self.assertIsNone(i["distance_km"])
        self.assertAlmostEqual(i["ra"], 88.79, delta=0.05)
        self.assertAlmostEqual(i["dec"], 7.41, delta=0.05)

    def test_lune(self):
        pleine = astro.infos("moon", *PARIS, instant(2026, 10, 26, 4, 12))  # pleine Lune
        nouvelle = astro.infos("moon", *PARIS, instant(2026, 10, 10, 15, 50))  # nouvelle Lune
        self.assertGreater(pleine["eclairement"], 0.99)
        self.assertLess(nouvelle["eclairement"], 0.01)
        self.assertTrue(356_000 < pleine["distance_km"] < 407_000)
        self.assertIsNone(pleine["magnitude"])

    def test_venus_plus_brillante_que_mars(self):
        t = instant(2026, 10, 29)
        self.assertLess(astro.infos("venus", *PARIS, t)["magnitude"], astro.infos("mars barycenter", *PARIS, t)["magnitude"])


class FicheTests(TestCase):
    def test_ce_soir(self):
        saturne = ObjetCeleste.objects.create(nom="Saturne", categorie="planete", identifiant_skyfield="saturn barycenter")
        d = self.client.get(f"/api/ciel/objets/{saturne.id}/", {"instant": "2026-10-29T12:00:00Z"}).json()
        soir = d["ce_soir"]
        self.assertTrue(soir["debut_nuit"] < soir["fin_nuit"])
        v = soir["visible"]
        self.assertEqual({"de", "a", "hauteur_max", "instant"}, set(v))
        self.assertTrue(soir["debut_nuit"] <= v["de"] <= v["instant"] <= v["a"] <= soir["fin_nuit"])
        self.assertGreaterEqual(v["hauteur_max"], 10)
        self.assertEqual(d["constellation_iau"], "Cet")  # Saturne dans la Baleine fin 2026

    def test_pas_visible_ce_soir(self):
        # Sirius ne monte pas à 10° pendant la nuit vue de Paris en juin
        sirius = ObjetCeleste.objects.create(nom="Sirius", categorie="etoile", identifiant_skyfield="hip:32349")
        d = self.client.get(f"/api/ciel/objets/{sirius.id}/", {"instant": "2026-06-15T12:00:00Z"}).json()
        self.assertIsNone(d["ce_soir"]["visible"])
        self.assertEqual(d["constellation_iau"], "CMa")


class PointDuCielTests(TestCase):
    """Partie 8.4 : /api/ciel/point/ décrit un point quelconque du ciel."""

    def test_point_aux_coordonnees_de_betelgeuse(self):
        d = self.client.get("/api/ciel/point/", {"ra": 88.7929, "dec": 7.4071, "instant": "2026-10-12T23:00:00Z"}).json()
        self.assertEqual({"ra", "dec", "instant", "elevation", "azimut", "visible", "constellation_iau", "ce_soir"}, set(d))
        elevation, azimut = astro.altaz("hip:27989", *PARIS, instant(2026, 10, 12, 23))
        self.assertAlmostEqual(d["elevation"], elevation, delta=0.02)
        self.assertAlmostEqual(d["azimut"], azimut, delta=0.02)
        self.assertEqual(d["constellation_iau"], "Ori")

    def test_parametres(self):
        for params in [{}, {"ra": 10}, {"ra": "x", "dec": 1}, {"ra": 10, "dec": 91}, {"ra": "nan", "dec": 1}]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/api/ciel/point/", params).status_code, 400)

    def test_identifiant_invalide(self):
        with self.assertRaises(ValueError):
            astro.altaz("radec:abc", *PARIS)

"""Partie 14.1 bis : aperçu d'une visite guidée (horaires et hauteurs), à date fixe.

    python manage.py test appareil.test_apercu
"""

from datetime import datetime, timedelta, timezone

from django.test import TestCase, override_settings

from ciel.astro import altaz, instant_depuis
from ciel.models import ObjetCeleste

PARIS = {"latitude": 48.8566, "longitude": 2.3522, "altitude_m": 35}
URL = "/api/pointage/visite/apercu/"
DEBUT = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)


@override_settings(LIEU_PAR_DEFAUT=PARIS)
class ApercuVisiteTests(TestCase):
    def setUp(self):
        self.jupiter = ObjetCeleste.objects.create(nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter")

    def apercu(self, corps):
        return self.client.post(URL, corps, content_type="application/json")

    def test_horaires_enchaines_et_hauteurs(self):
        r = self.apercu({"debut": "2026-10-12T20:00:00Z", "etapes": [
            {"objet_id": self.jupiter.id, "duree_min": 10},
            {"ra": 100.0, "dec": -80.0, "duree_min": 5},  # près du pôle Sud : jamais levé à Paris
            {"objet_id": 999999, "duree_min": 15},  # inconnu
        ]})
        self.assertEqual(r.status_code, 200)
        e = r.json()["etapes"]
        self.assertEqual(len(e), 3)
        cles = {"debut", "fin", "hauteur_debut", "hauteur_fin", "hauteur_min", "sous_horizon"}
        self.assertTrue(all(set(x) == cles for x in e))
        debuts = [datetime.fromisoformat(x["debut"]) for x in e]
        self.assertEqual(debuts, [DEBUT, DEBUT + timedelta(minutes=10), DEBUT + timedelta(minutes=15)])
        self.assertEqual(datetime.fromisoformat(e[2]["fin"]), DEBUT + timedelta(minutes=30))
        # Jupiter : la hauteur annoncée au début de l'étape est celle de Skyfield
        attendu, _ = altaz("jupiter barycenter", PARIS["latitude"], PARIS["longitude"], PARIS["altitude_m"], instant_depuis(DEBUT))
        self.assertAlmostEqual(e[0]["hauteur_debut"], attendu, delta=0.1)
        self.assertEqual(e[0]["sous_horizon"], e[0]["hauteur_min"] < 0)
        self.assertTrue(e[1]["sous_horizon"])
        self.assertLess(e[1]["hauteur_min"], 0)
        self.assertIsNone(e[2]["hauteur_min"])
        self.assertFalse(e[2]["sous_horizon"])

    def test_sans_code_de_pilotage_et_lecture_seule(self):
        r = self.apercu({"debut": None, "etapes": [{"objet_id": self.jupiter.id, "duree_min": 5}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_corps_invalides(self):
        for corps in [{}, {"etapes": []}, {"etapes": [{"objet_id": self.jupiter.id, "duree_min": 0}]},
                      {"etapes": [{"objet_id": self.jupiter.id}]}, {"debut": "hier", "etapes": [{"ra": 1, "dec": 2, "duree_min": 5}]},
                      {"debut": "2026-10-12T20:00:00", "etapes": [{"ra": 1, "dec": 2, "duree_min": 5}]}, [1]]:
            self.assertEqual(self.apercu(corps).status_code, 400, corps)

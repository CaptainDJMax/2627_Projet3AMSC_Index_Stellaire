"""Partie 14 : refus de pointer vers le Soleil (dates fixes, aucun accès à internet).

    python manage.py test appareil.test_securite
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import TestCase, override_settings

from ciel import astro
from ciel.models import ObjetCeleste

from . import securite
from .models import Appareil

PARIS = {"latitude": 48.8566, "longitude": 2.3522, "altitude_m": 35}
CODE_TEST = "code-de-test-securite"
MIDI = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)  # Soleil levé à Paris
MINUIT = datetime(2026, 10, 30, 23, 0, tzinfo=timezone.utc)  # Soleil couché depuis longtemps


def position_du_soleil(quand):
    return astro.radec("sun", PARIS["latitude"], PARIS["longitude"], PARIS["altitude_m"], astro.instant_depuis(quand))


class SeparationTests(TestCase):
    def test_le_soleil_lui_meme(self):
        self.assertEqual(securite.separation_mini("sun", PARIS, MIDI, 3600), 0.0)
        with self.assertRaises(securite.TropPresDuSoleil):
            securite.verifier("sun", "Soleil", PARIS, MIDI, 48 * 3600)

    def test_point_a_cote_du_soleil_en_plein_jour(self):
        ra, dec = position_du_soleil(MIDI)
        sep = securite.separation_mini(f"radec:{ra},{dec + 3}", PARIS, MIDI, 3600)
        self.assertAlmostEqual(sep, 3.0, delta=0.3)
        with self.assertRaises(securite.TropPresDuSoleil) as e:
            securite.verifier(f"radec:{ra},{dec + 3}", "Mon point", PARIS, MIDI, 3600)
        self.assertIn("Mon point", str(e.exception))

    def test_la_nuit_viser_vers_le_soleil_c_est_viser_le_sol(self):
        ra, dec = position_du_soleil(MINUIT)
        self.assertEqual(securite.separation_mini(f"radec:{ra},{dec}", PARIS, MINUIT, 3600), 180.0)

    def test_planete_proche_du_soleil(self):
        """Conjonction de Mars avec le Soleil le 9 janvier 2026 : refusée ; Jupiter fin octobre 2026 : acceptée."""
        quand = datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc)
        self.assertLess(securite.separation_mini("mars barycenter", PARIS, quand, 48 * 3600), securite.ANGLE_MINI_SOLEIL)
        self.assertGreater(securite.separation_mini("jupiter barycenter", PARIS, MIDI, 48 * 3600), 60)

    def test_visite_chaque_etape_sur_sa_fenetre(self):
        ra, dec = position_du_soleil(MIDI + timedelta(hours=1))
        etapes = [
            {"identifiant": "jupiter barycenter", "nom": "Jupiter", "duree_s": 3600},
            {"identifiant": f"radec:{ra},{dec}", "nom": "Près du Soleil", "duree_s": 600},
            {"identifiant": "jupiter barycenter", "nom": "Jupiter", "duree_s": 600},
        ]
        with self.assertRaises(securite.TropPresDuSoleil) as e:
            securite.verifier_visite(etapes, PARIS, MIDI)
        self.assertIn("Près du Soleil", str(e.exception))


@override_settings(CODE_PILOTAGE=CODE_TEST, LIEU_PAR_DEFAUT=PARIS)
class ApiRefusSoleilTests(TestCase):
    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.client.post("/api/pointage/pilotage/", {"code": CODE_TEST}, content_type="application/json")
        self.soleil = ObjetCeleste.objects.create(nom="Soleil", categorie="soleil", identifiant_skyfield="sun")
        self.jupiter = ObjetCeleste.objects.create(nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter")

    def poster(self, url, corps, quand=MIDI):
        with patch("appareil.views.timezone.now", return_value=quand):
            return self.client.post(url, corps, content_type="application/json")

    def test_commande_vers_le_soleil_refusee(self):
        r = self.poster("/api/pointage/commande/", {"objet_id": self.soleil.id})
        self.assertEqual(r.status_code, 422)
        d = r.json()
        self.assertEqual({"erreur", "soleil"}, set(d))
        self.assertEqual({"separation_deg", "minimum_deg"}, set(d["soleil"]))
        self.assertIsNone(self.appareil.commandes.filter(active=True).first())  # rien n'a été commandé

    def test_point_pres_du_soleil_refuse_et_planete_acceptee(self):
        ra, dec = position_du_soleil(MIDI)
        self.assertEqual(self.poster("/api/pointage/commande/", {"ra": ra, "dec": dec + 5}).status_code, 422)
        self.assertEqual(self.poster("/api/pointage/commande/", {"objet_id": self.jupiter.id}).status_code, 200)

    def test_visite_avec_le_soleil_refusee(self):
        r = self.poster("/api/pointage/visite/", {"debut": None, "etapes": [
            {"objet_id": self.jupiter.id, "duree_min": 10},
            {"objet_id": self.soleil.id, "duree_min": 10},
        ]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("Soleil", r.json()["erreur"])

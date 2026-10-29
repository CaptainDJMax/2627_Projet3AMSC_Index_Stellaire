"""Partie 7 : événements visibles à l'œil nu.

Les dates de référence viennent de sources extérieures, pas de notre propre calcul :
- essaims : calendrier 2026 de l'IMO (Géminides le 14 décembre, Perséides le 13 août) ;
- éclipse de Lune partielle du 28 août 2026, maximum vers 04 h 13 UTC ;
- rapprochement de Vénus et Jupiter le 9 juin 2026 (environ 1,6°).

    python manage.py test ciel
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import TestCase, override_settings

from . import astro, evenements
from .models import ObjetCeleste
from .test_satellites import DossierTleTemporaire, fabriquer_tle

PARIS = (48.8566, 2.3522, 35)


def instant(*args):
    return astro.instant_depuis(datetime(*args, tzinfo=timezone.utc))


def heure(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


ASTRES = [
    (1, "Lune", "moon", "lune"),
    (2, "Vénus", "venus", "planete"),
    (3, "Jupiter", "jupiter barycenter", "planete"),
    (4, "Mars", "mars barycenter", "planete"),
    (5, "Saturne", "saturn barycenter", "planete"),
]


class EssaimsTests(TestCase):
    def test_dates_du_calendrier_imo(self):
        for nom, attendu in [("Géminides", datetime(2026, 12, 14)), ("Perséides", datetime(2026, 8, 13))]:
            longitude = next(e[1] for e in evenements.ESSAIMS if e[0] == nom)
            maxima = evenements.maximum_essaim(longitude, instant(2026, 1, 1), instant(2027, 1, 1))
            with self.subTest(essaim=nom):
                self.assertEqual(len(maxima), 1)
                self.assertEqual(maxima[0].utc_datetime().date(), attendu.date())

    def test_evenement_de_nuit_radiant_leve(self):
        liste = evenements.essaims(*PARIS, instant(2026, 12, 10), instant(2026, 12, 17))
        self.assertEqual([e["titre"] for e in liste], ["Géminides"])
        e = liste[0]
        self.assertEqual(e["zhr"], 150)
        self.assertGreater(e["direction"]["elevation"], 20)  # le radiant est haut
        soleil = evenements._hauteur_soleil(astro.wgs84.latlon(*PARIS[:2], elevation_m=35),
                                            astro.instant_depuis(heure(e["instant"])))
        self.assertLess(soleil, evenements.SOLEIL_NUIT_NOIRE)
        self.assertIsInstance(e["lune_genante"], bool)


class LuneTests(TestCase):
    def test_phases(self):
        liste = evenements.phases_lune(*PARIS, instant(2026, 10, 1), instant(2026, 10, 31), lune_id=1)
        self.assertEqual(len(liste), 4)
        self.assertEqual(sorted(e["phase"] for e in liste), [0, 1, 2, 3])
        self.assertTrue(all(e["objet_id"] == 1 and e["type"] == "phase_lune" for e in liste))
        pleine = next(e for e in liste if e["phase"] == 2)
        self.assertEqual(pleine["titre"], "Pleine Lune")
        self.assertEqual(heure(pleine["instant"]).date(), datetime(2026, 10, 26).date())

    def test_eclipse_du_28_aout_2026(self):
        liste = evenements.eclipses_lune(*PARIS, instant(2026, 8, 25), instant(2026, 9, 1), lune_id=1)
        self.assertEqual(len(liste), 1)
        e = liste[0]
        self.assertEqual(e["titre"], "Éclipse de Lune partielle")
        self.assertAlmostEqual(heure(e["instant"]).timestamp(),
                               datetime(2026, 8, 28, 4, 13, tzinfo=timezone.utc).timestamp(), delta=10 * 60)
        self.assertGreater(e["direction"]["elevation"], 0)  # Lune encore levée à Paris

    def test_eclipse_invisible_si_lune_couchee(self):
        # À Tokyo, la Lune est couchée au maximum (13 h 13 heure locale)
        self.assertEqual(evenements.eclipses_lune(35.68, 139.69, 40, instant(2026, 8, 25), instant(2026, 9, 1)), [])


class ConjonctionsTests(TestCase):
    def test_venus_jupiter_juin_2026(self):
        liste = evenements.conjonctions(ASTRES, *PARIS, instant(2026, 6, 6), instant(2026, 6, 12))
        vj = [e for e in liste if set(e["objets"]) == {2, 3}]
        self.assertEqual(len(vj), 1)
        self.assertEqual(heure(vj[0]["instant"]).date(), datetime(2026, 6, 9).date())
        self.assertLess(vj[0]["ecart"], 2.5)

    def test_observable_seulement(self):
        lieu = astro.wgs84.latlon(*PARIS[:2], elevation_m=35)
        for e in evenements.conjonctions(ASTRES, *PARIS, instant(2026, 10, 25), instant(2026, 11, 25)):
            t = astro.instant_depuis(heure(e["instant"]))
            with self.subTest(e=e["titre"]):
                self.assertLess(evenements._hauteur_soleil(lieu, t), evenements.SOLEIL_NUIT)
                seuil = evenements.ECART_LUNE_PLANETE if 1 in e["objets"] else evenements.ECART_PLANETES
                self.assertLessEqual(e["ecart"], seuil + 0.5)
                for a in ASTRES:
                    if a[0] in e["objets"]:
                        self.assertGreaterEqual(astro.altaz(a[2], *PARIS, t)[0], evenements.HAUTEUR_MINI_CONJONCTION - 0.1)
                if 1 in e["objets"]:
                    self.assertTrue(e["titre"].startswith("Lune et "))  # la Lune en premier


class CeSoirTests(TestCase):
    def test_nuit_et_astres(self):
        soir = evenements.ce_soir([a[:3] for a in ASTRES], *PARIS, instant(2026, 10, 29, 12))
        debut, fin = heure(soir["debut_nuit"]), heure(soir["fin_nuit"])
        self.assertTrue(16 <= debut.hour <= 18)  # le soir (UTC), fin octobre à Paris
        self.assertTrue(5 <= fin.hour <= 7)
        for a in soir["astres"]:
            self.assertGreaterEqual(a["hauteur_max"], evenements.HAUTEUR_MINI)
            self.assertTrue(soir["debut_nuit"] <= a["de"] <= a["instant"] <= a["a"] <= soir["fin_nuit"])
        self.assertIn("Saturne", [a["nom"] for a in soir["astres"]])

    def test_nuit_deja_commencee(self):
        soir = evenements.ce_soir([], *PARIS, instant(2026, 10, 29, 22))
        self.assertEqual(heure(soir["debut_nuit"]).hour, 22)  # la nuit en cours, pas la suivante

    def test_pas_de_nuit(self):
        # Été au-delà du cercle polaire : le Soleil ne descend pas à -6°
        soir = evenements.ce_soir([], 78.2, 15.6, 0, instant(2026, 6, 21))
        self.assertEqual(soir, {"debut_nuit": None, "fin_nuit": None, "astres": []})


class PassagesTests(DossierTleTemporaire, TestCase):
    def test_seulement_les_passages_visibles_et_hauts(self):
        epoque = datetime.now(timezone.utc).replace(microsecond=0)
        with patch("ciel.satellites._telecharger", return_value=fabriquer_tle(epoque)):
            debut = astro.instant_depuis(epoque)
            liste = evenements.passages_visibles([(9, "ISS", "sat:25544")], *PARIS, debut,
                                                 astro.instant_depuis(epoque + timedelta(days=7)))
            tous = astro.passages("sat:25544", *PARIS, debut, 7 * 24)
        attendus = [p["culmination"] for p in tous if p["visible"] and p["hauteur_max"] >= 20]
        self.assertEqual([e["instant"] for e in liste], attendus)
        self.assertTrue(all(e["objet_id"] == 9 and e["titre"] == "Passage de ISS" for e in liste))

    def test_pas_de_passage_loin_de_l_epoque_du_tle(self):
        epoque = datetime.now(timezone.utc).replace(microsecond=0)
        with patch("ciel.satellites._telecharger", return_value=fabriquer_tle(epoque)):
            loin = astro.instant_depuis(epoque + timedelta(days=20))
            liste = evenements.passages_visibles([(9, "ISS", "sat:25544")], *PARIS, loin,
                                                 astro.instant_depuis(epoque + timedelta(days=27)))
        self.assertEqual(liste, [])

    def test_sans_tle(self):
        with patch("ciel.satellites._telecharger", side_effect=OSError("réseau coupé")):
            self.assertEqual(evenements.passages_visibles([(9, "ISS", "sat:25544")], *PARIS,
                                                          instant(2026, 10, 29), instant(2026, 11, 5)), [])


class ApiEvenementsTests(DossierTleTemporaire, TestCase):
    URL = "/api/ciel/evenements/"

    def setUp(self):
        super().setUp()
        for _, nom, ident, cat in ASTRES:
            ObjetCeleste.objects.create(nom=nom, categorie=cat, identifiant_skyfield=ident)
        ObjetCeleste.objects.create(nom="Véga", categorie="etoile", identifiant_skyfield="hip:91262")
        ObjetCeleste.objects.create(nom="ISS", categorie="satellite", identifiant_skyfield="sat:25544")
        for cible in ("ciel.satellites._telecharger", "ciel.sources_externes._telecharger"):
            patcher = patch(cible, side_effect=OSError("pas de réseau en test"))
            patcher.start()
            self.addCleanup(patcher.stop)
        reglage = override_settings(DOSSIER_SOURCES_EXTERNES=self._dossier.name)
        reglage.enable()
        self.addCleanup(reglage.disable)

    def test_contrat(self):
        d = self.client.get(self.URL, {"instant": "2026-08-25T00:00:00Z"}).json()
        self.assertEqual({"instant", "jours", "lieu", "ce_soir", "evenements", "sources"}, set(d))  # sources : 8.3
        for s in d["sources"]:
            self.assertEqual({"nom", "page", "licence", "etat", "age_h"}, set(s))
        self.assertEqual(d["sources"][0]["etat"], "ok")  # le calcul interne marche toujours
        self.assertEqual(d["jours"], 7)
        self.assertEqual({"debut_nuit", "fin_nuit", "astres"}, set(d["ce_soir"]))
        for a in d["ce_soir"]["astres"]:
            self.assertEqual({"objet_id", "nom", "de", "a", "hauteur_max", "instant", "direction"}, set(a))
            self.assertNotEqual(a["nom"], "Véga")  # ce soir : Lune et planètes seulement
        types = {e["type"] for e in d["evenements"]}
        self.assertIn("eclipse_lune", types)
        self.assertIn("phase_lune", types)
        for e in d["evenements"]:
            with self.subTest(e=e["titre"]):
                self.assertTrue({"type", "titre", "instant", "objet_id", "direction", "important", "source"} <= set(e))
                self.assertIn(e["type"], {"phase_lune", "conjonction", "essaim", "eclipse_lune", "passage",
                                          "eclipse_soleil", "opposition", "elongation", "occultation", "saison",
                                          "aurore", "comete"})
                self.assertIsInstance(e["important"], bool)
        instants = [e["instant"] for e in d["evenements"]]
        self.assertEqual(instants, sorted(instants))
        lune = ObjetCeleste.objects.get(nom="Lune").id
        self.assertTrue(all(e["objet_id"] == lune for e in d["evenements"] if e["type"] == "eclipse_lune"))

    def test_parametres(self):
        self.assertEqual(self.client.get(self.URL, {"jours": "abc"}).status_code, 400)
        self.assertEqual(self.client.get(self.URL, {"instant": "hier"}).status_code, 400)
        self.assertEqual(self.client.get(self.URL, {"jours": 99, "instant": "2026-10-01T00:00:00Z"}).json()["jours"], 31)
        self.assertEqual(self.client.post(self.URL).status_code, 405)

    def test_sans_tle_les_autres_evenements_restent(self):
        reponse = self.client.get(self.URL, {"instant": "2026-12-10T00:00:00Z"})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("Géminides", [e["titre"] for e in reponse.json()["evenements"]])

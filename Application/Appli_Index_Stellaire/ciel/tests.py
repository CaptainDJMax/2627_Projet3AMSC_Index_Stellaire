"""Tests de l'API du ciel.

Ils verrouillent le « contrat » dont dépend le JavaScript de la carte : tant que ces
tests passent, on peut refaire l'interface (étape 3.5) sans casser les données.

    python manage.py test ciel
"""

import json
import logging
from pathlib import Path

from django.contrib.staticfiles import finders
from django.test import TestCase

from .models import Constellation, ObjetCeleste

CLES_LISTE = {"id", "nom", "categorie", "elevation", "azimut", "ra", "dec", "visible"}
CLES_DETAIL = {
    "id", "nom", "categorie", "description", "image", "constellations",
    "instant", "lieu", "position", "levers_couchers", "trajectoire",
}


class ApiCielTests(TestCase):
    def setUp(self):
        logging.disable(logging.WARNING)  # les identifiants invalides sont volontaires ici
        self.addCleanup(logging.disable, logging.NOTSET)

    @classmethod
    def setUpTestData(cls):
        # Planètes et Lune : calculées avec l'éphéméride seule (pas besoin du catalogue d'étoiles)
        cls.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter",
            description="Géante gazeuse.",
        )
        cls.lune = ObjetCeleste.objects.create(nom="Lune", categorie="lune", identifiant_skyfield="moon")
        cls.sans_id = ObjetCeleste.objects.create(nom="Amas sans identifiant", categorie="amas")
        cls.invalide = ObjetCeleste.objects.create(
            nom="Planète fantôme", categorie="planete", identifiant_skyfield="pluton-imaginaire"
        )
        constellation = Constellation.objects.create(nom="Cancer")
        constellation.etoiles.set([])

    # --- Liste -------------------------------------------------------------

    def test_liste_contrat_et_filtrage(self):
        reponse = self.client.get("/api/ciel/objets/")
        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()
        self.assertEqual({"instant", "lieu", "objets"}, set(donnees))
        # Seuls les objets calculables sont renvoyés : ni sans identifiant, ni invalide
        self.assertEqual({o["nom"] for o in donnees["objets"]}, {"Jupiter", "Lune"})
        for o in donnees["objets"]:
            self.assertEqual(CLES_LISTE, set(o))
            self.assertTrue(0 <= o["ra"] < 360)
            self.assertTrue(-90 <= o["dec"] <= 90)
            self.assertTrue(-90 <= o["elevation"] <= 90)
            self.assertEqual(o["visible"], o["elevation"] > 0)

    def test_liste_a_un_instant_donne(self):
        reponse = self.client.get("/api/ciel/objets/?instant=2026-10-12T12:00:00Z")
        self.assertEqual(reponse.json()["instant"], "2026-10-12T12:00:00Z")

    def test_liste_instant_sans_fuseau_est_pris_en_utc(self):
        reponse = self.client.get("/api/ciel/objets/?instant=2026-10-12T12:00:00")
        self.assertEqual(reponse.json()["instant"], "2026-10-12T12:00:00Z")

    def test_liste_instant_invalide(self):
        for valeur in ("bidon", "2300-01-01T00:00:00Z", "1900-01-01T00:00:00Z"):
            with self.subTest(valeur=valeur):
                reponse = self.client.get("/api/ciel/objets/", {"instant": valeur})
                self.assertEqual(reponse.status_code, 400)
                self.assertIn("erreur", reponse.json())

    def test_liste_refuse_les_ecritures(self):
        self.assertEqual(self.client.post("/api/ciel/objets/").status_code, 405)

    # --- Détail ------------------------------------------------------------

    def test_detail_contrat(self):
        reponse = self.client.get(f"/api/ciel/objets/{self.jupiter.id}/")
        self.assertEqual(reponse.status_code, 200)
        d = reponse.json()
        self.assertEqual(CLES_DETAIL, set(d))
        self.assertEqual(d["nom"], "Jupiter")
        self.assertEqual(d["description"], "Géante gazeuse.")
        self.assertIsNone(d["image"])
        self.assertEqual({"elevation", "azimut", "visible"}, set(d["position"]))
        self.assertIn(len(d["trajectoire"]), (144, 145))  # 24 h, un point toutes les 10 min
        for e in d["levers_couchers"]:
            self.assertIn(e["evenement"], ("lever", "coucher"))

    def test_detail_bornes_duree_et_pas(self):
        d = self.client.get(f"/api/ciel/objets/{self.jupiter.id}/?duree=1&pas=60").json()
        self.assertIn(len(d["trajectoire"]), (1, 2))  # 1 h, un point par heure
        # Valeurs absurdes : ramenées aux bornes, pas d'erreur
        d = self.client.get(f"/api/ciel/objets/{self.jupiter.id}/?duree=9999&pas=abc").json()
        self.assertIn(len(d["trajectoire"]), (432, 433))  # 72 h, pas par défaut de 10 min

    def test_detail_a_un_instant_donne(self):
        d = self.client.get(f"/api/ciel/objets/{self.jupiter.id}/?instant=2026-10-12T12:00:00Z").json()
        self.assertEqual(d["instant"], "2026-10-12T12:00:00Z")
        self.assertEqual(d["trajectoire"][0]["instant"], "2026-10-12T12:00:00Z")

    def test_detail_erreurs(self):
        self.assertEqual(self.client.get("/api/ciel/objets/99999/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/ciel/objets/{self.sans_id.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/ciel/objets/{self.invalide.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/ciel/objets/{self.jupiter.id}/?instant=bidon").status_code, 400)


class PageCarteTests(TestCase):
    def test_la_page_se_charge_et_transmet_le_lieu(self):
        reponse = self.client.get("/")
        self.assertEqual(reponse.status_code, 200)
        contenu = reponse.content.decode()
        self.assertIn('id="donnees-lieu"', contenu)
        for url in ("/api/pointage/", "/api/pointage/commande/", "/api/pointage/arret/"):
            self.assertIn(url, contenu)  # le JavaScript lit ces adresses dans la page
        self.assertIn("Europe/Paris", contenu)  # fuseau d'affichage
        self.assertIn('data-url-objets="/api/ciel/objets/"', contenu)
        self.assertIn("data-url-illustrations=", contenu)
        self.assertIn("data-dossier-illustrations=", contenu)
        self.assertIn("Johan Meuris", contenu)  # mention obligatoire de la Licence Art Libre


class IllustrationsTests(TestCase):
    """Le fichier d'ancrages des illustrations (étape 3.5.5) : format lu par carte.js."""

    def test_ancrages_et_images(self):
        chemin = finders.find("ciel/constellations/illustrations.json")
        self.assertIsNotNone(chemin)
        donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
        self.assertIn("Licence Art Libre", donnees["licence"])
        illustrations = donnees["illustrations"]
        self.assertEqual(len(illustrations), 84)
        dossier = Path(chemin).parent / "illustrations"
        for il in illustrations:
            self.assertTrue((dossier / il["fichier"]).is_file(), il["fichier"])
            self.assertEqual(len(il["ancrages"]), 3)
            self.assertEqual(len(il["taille"]), 2)
            self.assertTrue(10 <= il["rayon"] <= 60, il["iau"])  # degrés : taille de la figure dans le ciel
            for a in il["ancrages"]:
                self.assertTrue(-180 <= a["ra"] <= 360 and -90 <= a["dec"] <= 90, il["iau"])
                self.assertTrue(0 <= a["x"] <= il["taille"][0] and 0 <= a["y"] <= il["taille"][1], il["iau"])

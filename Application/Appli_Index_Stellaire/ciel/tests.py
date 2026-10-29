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
    "image_credit", "sources",  # ajoutés pour le contenu (crédits de l'image, sources du texte)
    "passages",  # Partie 6.3 : prochains passages d'un satellite (None pour les autres astres)
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
        self.assertIsNone(d["passages"])  # 6.3 : seulement pour un satellite
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
        for url in ("/api/pointage/", "/api/pointage/commande/", "/api/pointage/arret/",
                    "/api/pointage/pilotage/", "/api/pointage/pilotage/fin/"):
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


class ContenuTests(TestCase):
    """Commandes importer_contenu / exporter_contenu : le contenu partagé par Git (un fichier par astre)."""

    def setUp(self):
        import io
        import tempfile

        from django.test import override_settings
        from PIL import Image

        self._dossiers = tempfile.TemporaryDirectory()
        racine = Path(self._dossiers.name)
        self.contenu = racine / "contenu"
        (self.contenu / "astres").mkdir(parents=True)
        (self.contenu / "images").mkdir()
        tampon = io.BytesIO()
        Image.new("RGB", (8, 8), (200, 120, 40)).save(tampon, "PNG")
        (self.contenu / "images" / "venus.png").write_bytes(tampon.getvalue())
        self._media = override_settings(MEDIA_ROOT=str(racine / "media"))
        self._media.enable()

    def tearDown(self):
        self._media.disable()
        self._dossiers.cleanup()

    def ecrire(self, nom_fichier, donnees):
        (self.contenu / "astres" / nom_fichier).write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")

    def importer(self):
        import io

        from django.core.management import call_command

        sortie = io.StringIO()
        call_command("importer_contenu", dossier=str(self.contenu), stdout=sortie)
        return sortie.getvalue()

    VENUS = {
        "nom": "Vénus", "categorie": "planete", "identifiant_skyfield": "venus",
        "description": "Deuxième planète.", "sources": ["https://fr.wikipedia.org/wiki/V%C3%A9nus_(plan%C3%A8te)"],
        "image": "venus.png", "image_source": "https://images.nasa.gov/", "image_auteur": "NASA",
        "image_licence": "Domaine public", "constellations": [],
    }

    def test_import_cree_puis_ne_change_rien(self):
        self.ecrire("venus.json", self.VENUS)
        self.ecrire("aldebaran.json", {"nom": "Aldébaran", "categorie": "etoile", "identifiant_skyfield": "hip:21421",
                                       "constellations": ["Taureau"]})
        sortie = self.importer()
        self.assertIn("2 créés", sortie)
        venus = ObjetCeleste.objects.get(nom="Vénus")
        self.assertEqual(venus.image.name, "objets_celestes/venus.png")
        self.assertTrue(Path(venus.image.path).is_file())
        self.assertEqual(venus.image_licence, "Domaine public")
        self.assertEqual([c.nom for c in ObjetCeleste.objects.get(nom="Aldébaran").constellations.all()], ["Taureau"])
        # Un second import ne crée rien et ne modifie rien
        self.assertIn("0 créés, 0 mis à jour, 2 inchangés", self.importer())
        self.assertEqual(ObjetCeleste.objects.count(), 2)

    def test_le_fichier_fait_foi(self):
        self.ecrire("venus.json", self.VENUS)
        self.importer()
        self.ecrire("venus.json", {**self.VENUS, "description": "Texte corrigé."})
        self.assertIn("1 mis à jour", self.importer())
        self.assertEqual(ObjetCeleste.objects.get(nom="Vénus").description, "Texte corrigé.")

    def test_image_sans_credit_refusee_et_rien_importe(self):
        from django.core.management.base import CommandError

        self.ecrire("venus.json", {**self.VENUS, "image_licence": ""})
        self.ecrire("mars.json", {"nom": "Mars", "categorie": "planete", "identifiant_skyfield": "mars barycenter"})
        with self.assertRaises(CommandError) as erreur:
            self.importer()
        self.assertIn("image_licence", str(erreur.exception))
        self.assertEqual(ObjetCeleste.objects.count(), 0)  # tout ou rien

    def test_noms_en_double_et_champs_inconnus_refuses(self):
        from django.core.management.base import CommandError

        self.ecrire("a.json", {"nom": "Mars", "categorie": "planete"})
        self.ecrire("b.json", {"nom": "Mars", "categorie": "planete", "descritpion": "faute"})
        with self.assertRaises(CommandError) as erreur:
            self.importer()
        self.assertIn("descritpion", str(erreur.exception))

    def test_export_puis_reimport_identique(self):
        import io

        from django.core.management import call_command

        self.ecrire("venus.json", self.VENUS)
        self.importer()
        sortie = io.StringIO()
        call_command("exporter_contenu", dossier=str(self.contenu), stdout=sortie)
        exporte = json.loads((self.contenu / "astres" / "venus.json").read_text(encoding="utf-8"))
        self.assertEqual(exporte, self.VENUS)
        # Exporter sans rien changer ne réécrit aucun fichier (pas de faux changement pour Git)
        sortie = io.StringIO()
        call_command("exporter_contenu", dossier=str(self.contenu), stdout=sortie)
        self.assertIn("0 fichier(s) écrit(s)", sortie.getvalue())

    def test_credit_dans_l_api(self):
        self.ecrire("venus.json", self.VENUS)
        self.importer()
        venus = ObjetCeleste.objects.get(nom="Vénus")
        donnees = self.client.get(f"/api/ciel/objets/{venus.id}/").json()
        self.assertEqual(donnees["image_credit"], {"source": "https://images.nasa.gov/", "auteur": "NASA",
                                                   "licence": "Domaine public"})
        self.assertEqual(len(donnees["sources"]), 1)

    def test_conflit_git_explique(self):
        from django.core.management.base import CommandError

        (self.contenu / "astres" / "mars.json").write_text(
            '{\n  "nom": "Mars",\n<<<<<<< HEAD\n  "categorie": "planete"\n=======\n  "categorie": "planete"\n>>>>>>> abc\n}\n',
            encoding="utf-8",
        )
        with self.assertRaises(CommandError) as erreur:
            self.importer()
        self.assertIn("conflit Git non résolu", str(erreur.exception))


class LieuPartageTests(TestCase):
    """Partie 6.4 : position partagée par le navigateur, en secours du lieu par défaut."""

    @classmethod
    def setUpTestData(cls):
        cls.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter"
        )

    def _poster(self, corps):
        return self.client.post("/api/ciel/lieu/", corps, content_type="application/json")

    def test_partager_puis_utilisee_par_la_carte(self):
        reponse = self._poster({"latitude": -33.9, "longitude": 18.4, "altitude_m": 10})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(
            reponse.json()["lieu"], {"latitude": -33.9, "longitude": 18.4, "altitude_m": 10}
        )
        lieu = self.client.get("/api/ciel/objets/").json()["lieu"]
        self.assertEqual(lieu, {"latitude": -33.9, "longitude": 18.4, "altitude_m": 10})

    def test_retirer(self):
        self._poster({"latitude": -33.9, "longitude": 18.4, "altitude_m": 10})
        reponse = self._poster({"partager": False})
        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.json()["lieu"])
        from django.conf import settings
        self.assertEqual(self.client.get("/api/ciel/objets/").json()["lieu"], settings.LIEU_PAR_DEFAUT)

    def test_coordonnees_hors_limites_refusees(self):
        reponse = self._poster({"latitude": 120, "longitude": 18.4})
        self.assertEqual(reponse.status_code, 400)

    def test_corps_invalide_refuse(self):
        reponse = self._poster({"longitude": 18.4})  # latitude manquante
        self.assertEqual(reponse.status_code, 400)

    def test_sans_position_partagee_le_lieu_par_defaut_est_utilise(self):
        from django.conf import settings
        self.assertEqual(self.client.get("/api/ciel/objets/").json()["lieu"], settings.LIEU_PAR_DEFAUT)

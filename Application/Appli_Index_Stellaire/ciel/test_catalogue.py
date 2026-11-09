"""Catalogue automatique : base livrée, import, enrichissement Wikipédia/Commons (réseau simulé), carte.

    python manage.py test ciel.test_catalogue

Règle 11 : aucun accès à internet. _get_json et _get_octets sont remplacés par des réponses écrites ici.
"""

import io
import json
import tempfile
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from . import astro, catalogue
from .models import ObjetCeleste


def image_jpeg():
    sortie = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 50, 50)).save(sortie, "JPEG")
    return sortie.getvalue()


IMAGE_COMMONS = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Betelgeuse_photo.jpg/320px-Betelgeuse_photo.jpg"


def resume(titre, extrait, image=None, description="", type_="standard"):
    d = {"type": type_, "title": titre, "extract": extrait, "description": description,
         "content_urls": {"desktop": {"page": "https://fr.wikipedia.org/wiki/" + titre.replace(" ", "_")}}}
    if image:
        d["originalimage"] = {"source": image}
    return d


def commons(licence, artiste="<a href='x'>Jean Dupont</a>"):
    return {"query": {"pages": [{"imageinfo": [{
        "thumburl": "https://upload.wikimedia.org/x/800px-photo.jpg", "url": "https://upload.wikimedia.org/x/photo.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Betelgeuse_photo.jpg",
        "extmetadata": {"LicenseShortName": {"value": licence}, "Artist": {"value": artiste}},
    }]}]}}


class FauxWeb:
    """Répond aux adresses comme le feraient Wikipédia et Commons."""

    def __init__(self, pages, licence="CC BY-SA 4.0"):
        self.pages = pages  # titre -> réponse JSON du résumé (absent = 404)
        self.licence = licence
        self.appels = []

    def get_json(self, url):
        self.appels.append(url)
        if "commons.wikimedia.org/w/api.php" in url:
            return commons(self.licence)
        titre = url.rsplit("/", 1)[1]
        from urllib.parse import unquote
        titre = unquote(titre).replace("_", " ")
        if titre not in self.pages:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return self.pages[titre]

    def get_octets(self, url):
        return image_jpeg()


class DossierTemporaire:
    """BASE_DIR et MEDIA_ROOT dans un dossier temporaire (donnees_catalogue/, media/)."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        reglages = override_settings(BASE_DIR=self.tmp, MEDIA_ROOT=self.tmp / "media")
        reglages.enable()
        self.addCleanup(reglages.disable)
        pause = patch.object(catalogue, "PAUSE_S", 0)
        pause.start()
        self.addCleanup(pause.stop)


class BaseLivreeTests(TestCase):
    def test_contenu_de_la_base(self):
        base = catalogue.charger_base()
        par_categorie = {}
        for a in base:
            par_categorie.setdefault(a["categorie"], []).append(a)
        self.assertEqual(len([a for a in base if a["cle"].startswith("hip:")]), 919)
        self.assertEqual(len([a for a in base if a["cle"].startswith("M")]), 110)
        self.assertEqual({a["nom"] for a in par_categorie["planete"]},
                         {"Mercure", "Vénus", "Mars", "Jupiter", "Saturne", "Uranus", "Neptune", "Pluton"})
        self.assertEqual(len({a["cle"] for a in base}), len(base))
        self.assertEqual(len({a["nom"] for a in base}), len(base))  # noms uniques
        for a in base:
            self.assertTrue(a["wikipedia"], a["cle"])
            if a["identifiant"].startswith("radec:"):
                ra, dec = (float(x) for x in a["identifiant"][6:].split(","))
                self.assertTrue(0 <= ra < 360 and -90 <= dec <= 90)
                self.assertIn(a["forme"]["type"], ("ellipse", "amas"))
        betelgeuse = next(a for a in base if a["cle"] == "hip:27989")
        self.assertEqual((betelgeuse["nom"], betelgeuse["designation"]), ("Bételgeuse", "α Orionis"))
        self.assertEqual(betelgeuse["wikipedia"][0], "Alpha Orionis")
        m31 = next(a for a in base if a["cle"] == "M31")
        self.assertEqual(m31["forme"]["teinte"], "galaxie")
        self.assertAlmostEqual(m31["forme"]["grand_axe"], 3.0, delta=0.3)


class ImportTests(DossierTemporaire, TestCase):
    def test_import_hors_ligne_et_priorite_du_contenu(self):
        sirius = ObjetCeleste.objects.create(nom="Sirius", categorie="etoile", identifiant_skyfield="hip:32349",
                                             description="Écrit à la main.")
        ObjetCeleste.objects.create(nom="Galaxie d'Andromède", categorie="ciel_profond",
                                    identifiant_skyfield="radec:10.6846,41.2692")
        r = catalogue.mettre_a_jour(hors_ligne=True)
        self.assertEqual(r["ignores"], 2)  # Sirius (même identifiant), M31 (même point du ciel)
        self.assertEqual(r["crees"], len(catalogue.charger_base()) - 2)
        self.assertFalse(r["reseau"])
        sirius.refresh_from_db()
        self.assertEqual((sirius.origine, sirius.description), ("contenu", "Écrit à la main."))
        rigel = ObjetCeleste.objects.get(cle_catalogue="hip:24436")
        self.assertEqual((rigel.origine, rigel.designation, rigel.categorie), ("catalogue", "β Orionis", "etoile"))
        self.assertIn("HYG", rigel.description_credit)
        m13 = ObjetCeleste.objects.get(cle_catalogue="M13")
        self.assertEqual(m13.forme["type"], "amas")
        # Deuxième passage : rien ne change
        r = catalogue.mettre_a_jour(hors_ligne=True)
        self.assertEqual((r["crees"], r["mis_a_jour"]), (0, 0))

    def test_une_fiche_ecrite_apres_coup_masque_l_astre_du_catalogue(self):
        catalogue.importer(catalogue.charger_base()[:200])
        rigel = ObjetCeleste.objects.get(cle_catalogue="hip:24436")
        ObjetCeleste.objects.create(nom="Rigel (à la main)", categorie="etoile", identifiant_skyfield="hip:24436")
        catalogue.importer(catalogue.charger_base()[:200])
        rigel.refresh_from_db()
        self.assertEqual(rigel.identifiant_skyfield, "")  # plus sur la carte, mais pas effacé
        self.assertTrue(ObjetCeleste.objects.filter(pk=rigel.pk).exists())

    def test_exporter_contenu_ignore_le_catalogue(self):
        catalogue.importer(catalogue.charger_base()[:5])
        ObjetCeleste.objects.create(nom="Sirius", categorie="etoile", identifiant_skyfield="hip:32349")
        sortie = self.tmp / "export"
        call_command("exporter_contenu", dossier=str(sortie), stdout=io.StringIO())
        self.assertEqual(sorted(p.name for p in (sortie / "astres").glob("*.json")), ["sirius.json"])

    def test_mise_a_jour_due(self):
        self.assertTrue(catalogue.mise_a_jour_due())
        catalogue._ecrire("etat.json", {"derniere_mise_a_jour": datetime.now(timezone.utc).isoformat()})
        self.assertFalse(catalogue.mise_a_jour_due())
        self.assertTrue(catalogue.mise_a_jour_due(datetime.now(timezone.utc) + timedelta(days=31)))


class EnrichissementTests(DossierTemporaire, TestCase):
    ASTRES = [
        {"cle": "hip:27989", "nom": "Bételgeuse", "designation": "α Orionis", "categorie": "etoile",
         "identifiant": "hip:27989", "magnitude": 0.45, "wikipedia": ["Alpha Orionis", "Bételgeuse"],
         "credit_donnees": "Base HYG"},
        {"cle": "hip:36850", "nom": "Castor", "designation": "α Geminorum", "categorie": "etoile",
         "identifiant": "hip:36850", "magnitude": 1.58, "wikipedia": ["Castor"], "credit_donnees": "Base HYG"},
    ]

    def lancer(self, web, **options):
        with patch.object(catalogue, "_get_json", web.get_json), patch.object(catalogue, "_get_octets", web.get_octets):
            return catalogue.enrichir(self.ASTRES, **options)

    def test_resume_image_et_credit(self):
        web = FauxWeb({
            "Alpha Orionis": resume("Bételgeuse", "Bételgeuse est une étoile supergéante rouge...", IMAGE_COMMONS),
            "Castor": resume("Castor (animal)", "Le castor est un rongeur semi-aquatique.", description="genre de rongeurs"),
        })
        stats = self.lancer(web)
        self.assertEqual((stats["textes"], stats["images"], stats["sans_article"]), (1, 1, 1))  # le rongeur est refusé
        catalogue.importer(self.ASTRES)
        b = ObjetCeleste.objects.get(cle_catalogue="hip:27989")
        self.assertTrue(b.description.startswith("Bételgeuse est une étoile"))
        self.assertIn("Wikipédia", b.description_credit)
        self.assertIn("CC BY-SA 4.0", b.description_credit)
        self.assertEqual(b.sources, "https://fr.wikipedia.org/wiki/Bételgeuse")
        self.assertEqual((b.image_auteur, b.image_licence), ("Jean Dupont", "CC BY-SA 4.0"))
        self.assertTrue(b.image.name.startswith("objets_celestes/catalogue/"))
        castor = ObjetCeleste.objects.get(cle_catalogue="hip:36850")
        self.assertIn("Le résumé de Wikipédia arrivera", castor.description)
        # Moins de 30 jours après : rien n'est redemandé
        web2 = FauxWeb({})
        self.assertEqual(self.lancer(web2)["deja_a_jour"], 2)
        self.assertEqual(web2.appels, [])

    def test_licences_refusees(self):
        for licence in ("CC BY-NC-SA 4.0", "CC BY-ND 2.0", "Fair use", ""):
            self.assertFalse(catalogue.licence_acceptee(licence), licence)
        for licence in ("CC BY-SA 4.0", "CC BY 2.0", "CC0", "Public domain", "PD-USGov-NASA"):
            self.assertTrue(catalogue.licence_acceptee(licence), licence)
        web = FauxWeb({"Alpha Orionis": resume("Bételgeuse", "Une étoile.", IMAGE_COMMONS)}, licence="CC BY-NC 2.0")
        self.assertEqual(self.lancer(web)["images"], 0)
        # Image propre à Wikipédia en français (pas sur Commons, souvent non libre) : ignorée
        self.assertIsNone(catalogue.fichier_commons("https://upload.wikimedia.org/wikipedia/fr/a/ab/Affiche.jpg"))
        self.assertEqual(catalogue.fichier_commons(IMAGE_COMMONS), "Betelgeuse_photo.jpg")

    def test_homonymie_refusee(self):
        web = FauxWeb({"Alpha Orionis": resume("Alpha", "étoile...", type_="disambiguation"),
                       "Bételgeuse": resume("Bételgeuse", "Bételgeuse est une étoile.")})
        self.lancer(web, limite=1)
        self.assertEqual(catalogue._lire("enrichissement.json", {})["hip:27989"]["titre"], "Bételgeuse")

    def test_sans_internet(self):
        def coupe(url):
            raise urllib.error.URLError("pas de réseau")

        with patch.object(catalogue, "_get_json", coupe):
            with self.assertRaises(catalogue.PasDeReseau):
                catalogue.enrichir(self.ASTRES * 6)
            r = catalogue.mettre_a_jour()  # importe quand même la base
        self.assertFalse(r["reseau"])
        self.assertGreater(r["crees"], 900)
        etat = catalogue.lire_etat()
        self.assertIn("dernier_echec", etat)
        self.assertNotIn("derniere_mise_a_jour", etat)  # on réessaiera au prochain démarrage


class CarteTests(TestCase):
    def test_positions_groupees_identiques_au_calcul_un_par_un(self):
        lieu = (48.85, 2.35, 35)
        t = astro.instant_depuis(datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc))
        idents = ["hip:32349", "radec:83.8187,-5.3897", "hip:999999999", "radec:abc"]
        r = astro.positions_fixes(idents, *lieu, t)
        self.assertEqual(set(r), {"hip:32349", "radec:83.8187,-5.3897"})  # les invalides sont absents
        for ident in r:
            el, az = astro.altaz(ident, *lieu, t)
            ra, dec = astro.radec(ident, *lieu, t)
            self.assertAlmostEqual(r[ident][0], el, places=6)
            self.assertAlmostEqual(r[ident][1], az, places=6)
            self.assertAlmostEqual(r[ident][2], ra, places=6)
            self.assertAlmostEqual(r[ident][3], dec, places=6)

    def test_api_champ_catalogue_credit_et_evenements(self):
        ObjetCeleste.objects.create(nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter")
        uranus = ObjetCeleste.objects.create(
            nom="Uranus", categorie="planete", identifiant_skyfield="uranus barycenter", origine="catalogue",
            cle_catalogue="planete:uranus", description_credit="Texte : Wikipédia en français, CC BY-SA 4.0",
        )
        m13 = ObjetCeleste.objects.create(
            nom="M13", categorie="amas", identifiant_skyfield="radec:250.4235,36.4613", origine="catalogue",
            cle_catalogue="M13", magnitude=5.8, designation="M13, NGC 6205", forme={"type": "amas", "diametre": 0.275},
        )
        objets = {o["nom"]: o for o in self.client.get("/api/ciel/objets/").json()["objets"]}
        self.assertNotIn("catalogue", objets["Jupiter"])
        self.assertIs(objets["Uranus"]["catalogue"], True)
        self.assertEqual(objets["M13"]["apparence"], {"type": "amas", "diametre": 0.275})
        d = self.client.get(f"/api/ciel/objets/{m13.id}/").json()
        self.assertEqual((d["magnitude"], d["designation"]), (5.8, "M13, NGC 6205"))
        d = self.client.get(f"/api/ciel/objets/{uranus.id}/").json()
        self.assertIn("Wikipédia", d["description_credit"])
        # Événements : le catalogue n'y entre pas (Uranus ne se voit pas à l'œil nu)
        with patch("ciel.sources_externes.evenements_externes", return_value=([], [])):
            ev = self.client.get("/api/ciel/evenements/?jours=1").json()
        self.assertNotIn("Uranus", [a["nom"] for a in ev["ce_soir"]["astres"]])

    def test_planetes_toujours_presentes_meme_sans_fiches(self):
        """Sans importer_contenu, les planètes viennent du catalogue ; Mars entre dans les événements."""
        tmp = Path(tempfile.mkdtemp())
        with override_settings(BASE_DIR=tmp, MEDIA_ROOT=tmp / "media"):
            catalogue.importer(catalogue.charger_base()[:8])
        noms = set(ObjetCeleste.objects.filter(categorie="planete").values_list("nom", flat=True))
        self.assertEqual(noms, {"Mercure", "Vénus", "Mars", "Jupiter", "Saturne", "Uranus", "Neptune", "Pluton"})
        pluton = ObjetCeleste.objects.get(nom="Pluton")
        self.assertEqual(self.client.get(f"/api/ciel/objets/{pluton.id}/").json()["magnitude"], 14.4)
        with patch("ciel.sources_externes.evenements_externes", return_value=([], [])):
            ev = self.client.get("/api/ciel/evenements/?jours=1&instant=2026-11-09T18:00:00Z").json()
        noms_soir = {a["nom"] for a in ev["ce_soir"]["astres"]}
        self.assertTrue(noms_soir & {"Mars", "Jupiter", "Saturne", "Vénus", "Mercure"})
        self.assertFalse(noms_soir & {"Uranus", "Neptune", "Pluton"})

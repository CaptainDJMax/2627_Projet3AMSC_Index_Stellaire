"""Partie 6.2 : satellites (TLE, cache, calculs). Aucun accès réseau : CelesTrak est simulé.

    python manage.py test ciel
"""

import math
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from sgp4.api import WGS72, Satrec
from sgp4.exporter import export_tle

from . import astro, satellites
from .models import ObjetCeleste


def fabriquer_tle(epoque=None, numero=25544, nom="ISS (ZARYA)"):
    """Un TLE valide (orbite de type ISS) d'époque donnée, par défaut maintenant.
    Les tests ne peuvent pas télécharger le vrai : on le fabrique."""
    epoque = epoque or datetime.now(timezone.utc).replace(microsecond=0)
    jours = (epoque - datetime(1949, 12, 31, tzinfo=timezone.utc)).total_seconds() / 86400
    sat = Satrec()
    sat.sgp4init(WGS72, "i", numero, jours, 3e-5, 0.0, 0.0, 0.0005, math.radians(90),
                 math.radians(51.64), math.radians(0), 15.5 * 2 * math.pi / 1440, math.radians(200))
    sat.intldesg = "98067A"
    ligne1, ligne2 = export_tle(sat)
    return f"{nom}\n{ligne1}\n{ligne2}\n"


class DossierTleTemporaire:
    """Mixin : un dossier de cache vide pour chaque test."""

    def setUp(self):
        super().setUp()
        self._dossier = tempfile.TemporaryDirectory()
        self._reglage = override_settings(DOSSIER_TLE=self._dossier.name)
        self._reglage.enable()
        astro._satellite_depuis_tle.cache_clear()

    def tearDown(self):
        self._reglage.disable()
        self._dossier.cleanup()
        super().tearDown()


class LectureTleTests(SimpleTestCase):
    def test_tle_fabrique_valide(self):
        nom, l1, l2 = satellites.lire_tle(fabriquer_tle(), 25544)
        self.assertEqual(nom, "ISS (ZARYA)")
        self.assertEqual((len(l1), len(l2)), (69, 69))

    def test_somme_de_controle(self):
        _, l1, l2 = satellites.lire_tle(fabriquer_tle(), 25544)
        chiffre = str((int(l1[68]) + 1) % 10)
        with self.assertRaises(satellites.TleIndisponible):
            satellites.lire_tle(f"ISS\n{l1[:68]}{chiffre}\n{l2}", 25544)

    def test_refus_des_textes_invalides(self):
        for texte in ["", "<html>erreur</html>", "No GP data found", fabriquer_tle(numero=20580)]:
            with self.subTest(texte=texte[:20]), self.assertRaises(satellites.TleIndisponible):
                satellites.lire_tle(texte, 25544)

    def test_epoque(self):
        epoque = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
        _, l1, _ = satellites.lire_tle(fabriquer_tle(epoque), 25544)
        self.assertAlmostEqual(satellites.epoque(l1), epoque.timestamp(), delta=0.01)

    def test_numero(self):
        self.assertEqual(satellites.numero_de("sat:25544"), 25544)
        self.assertIsNone(satellites.numero_de("hip:21421"))
        with self.assertRaises(satellites.TleIndisponible):
            satellites.numero_de("sat:iss")


class CacheTleTests(DossierTleTemporaire, SimpleTestCase):
    def test_telecharge_puis_garde_la_copie_locale(self):
        with patch("ciel.satellites._telecharger", return_value=fabriquer_tle()) as telechargement:
            d = satellites.tle(25544)
            satellites.tle(25544)
        telechargement.assert_called_once()  # une copie de moins de 6 h ne se retélécharge pas
        self.assertEqual({"numero", "nom", "ligne1", "ligne2", "epoque"}, set(d))
        self.assertTrue(d["epoque"].endswith("Z"))
        self.assertTrue(os.path.isfile(os.path.join(self._dossier.name, "25544.tle")))

    def test_copie_locale_si_celestrak_ne_repond_pas(self):
        with patch("ciel.satellites._telecharger", return_value=fabriquer_tle()):
            premier = satellites.tle(25544)
        fichier = os.path.join(self._dossier.name, "25544.tle")
        vieux = time.time() - 7 * 3600
        os.utime(fichier, (vieux, vieux))  # copie de plus de 6 h : on essaie de rafraîchir
        with patch("ciel.satellites._telecharger", side_effect=OSError("réseau coupé")) as telechargement:
            self.assertEqual(satellites.tle(25544), premier)
        telechargement.assert_called_once()

    def test_une_reponse_invalide_n_ecrase_pas_la_copie(self):
        with patch("ciel.satellites._telecharger", return_value=fabriquer_tle()):
            premier = satellites.tle(25544)
        fichier = os.path.join(self._dossier.name, "25544.tle")
        os.utime(fichier, (0, 0))
        with patch("ciel.satellites._telecharger", return_value="<html>Erreur 503</html>"):
            self.assertEqual(satellites.tle(25544), premier)

    def test_sans_reseau_ni_copie(self):
        with patch("ciel.satellites._telecharger", side_effect=OSError("réseau coupé")), \
                self.assertRaises(satellites.TleIndisponible):
            satellites.tle(25544)

    def test_tle_trop_ancien_refuse(self):
        ancien = datetime.now(timezone.utc) - timedelta(days=10)
        with patch("ciel.satellites._telecharger", return_value=fabriquer_tle(ancien)), \
                self.assertRaises(satellites.TleIndisponible):
            satellites.tle(25544)


class CalculSatelliteTests(DossierTleTemporaire, SimpleTestCase):
    LIEU = (48.8566, 2.3522, 35)

    def setUp(self):
        super().setUp()
        self.epoque = datetime.now(timezone.utc).replace(microsecond=0)
        self.texte = fabriquer_tle(self.epoque)
        patcher = patch("ciel.satellites._telecharger", return_value=self.texte)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_altaz_identique_au_calcul_du_robot(self):
        """Skyfield (serveur) et le calcul pas à pas du simulateur (= futur firmware) concordent."""
        from appareil.management.commands.simuler_appareil import position_sgp4

        _, l1, l2 = satellites.lire_tle(self.texte, 25544)
        lieu = dict(zip(("latitude", "longitude", "altitude_m"), self.LIEU))
        for minutes in range(0, 24 * 60, 37):
            t = self.epoque + timedelta(minutes=minutes)
            elevation, azimut = astro.altaz("sat:25544", *self.LIEU, astro.instant_depuis(t))
            robot = position_sgp4({"ligne1": l1, "ligne2": l2}, lieu, t.timestamp())
            with self.subTest(minutes=minutes):
                self.assertAlmostEqual(robot["elevation"], elevation, delta=0.05)
                ecart_az = abs((robot["azimut"] - azimut + 180) % 360 - 180) * math.cos(math.radians(elevation))
                self.assertLess(ecart_az, 0.05)

    def test_trajectoire_a_la_seconde_pres(self):
        debut = astro.instant_depuis(self.epoque)
        points = astro.trajectoire("sat:25544", *self.LIEU, debut, 1, 5 / 60)
        self.assertEqual(len(points), 721)  # 1 h, un point toutes les 5 s
        elevation, azimut = astro.altaz("sat:25544", *self.LIEU, astro.instant_depuis(self.epoque + timedelta(seconds=35)))
        self.assertAlmostEqual(points[7]["elevation"], elevation, delta=0.01)

    def test_passages(self):
        evenements = astro.levers_couchers("sat:25544", *self.LIEU, astro.instant_depuis(self.epoque), 24)
        self.assertGreater(len(evenements), 2)  # quelques passages par jour
        self.assertTrue(all(e["evenement"] in ("lever", "coucher") for e in evenements))
        sortes = [e["evenement"] for e in evenements]
        self.assertTrue(all(a != b for a, b in zip(sortes, sortes[1:])))  # lever, coucher, lever...

    def test_radec(self):
        ra, dec = astro.radec("sat:25544", *self.LIEU, astro.instant_depuis(self.epoque))
        self.assertTrue(0 <= ra < 360 and -90 <= dec <= 90)


class CarteSansTleTests(DossierTleTemporaire, TestCase):
    def test_l_iss_sans_tle_ne_casse_pas_la_carte(self):
        ObjetCeleste.objects.create(nom="ISS", categorie="satellite", identifiant_skyfield="sat:25544")
        ObjetCeleste.objects.create(nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter")
        with patch("ciel.satellites._telecharger", side_effect=OSError("réseau coupé")):
            reponse = self.client.get("/api/ciel/objets/")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual([o["nom"] for o in reponse.json()["objets"]], ["Jupiter"])

    def test_l_iss_avec_tle_sur_la_carte(self):
        ObjetCeleste.objects.create(nom="ISS", categorie="satellite", identifiant_skyfield="sat:25544")
        with patch("ciel.satellites._telecharger", return_value=fabriquer_tle()):
            objets = self.client.get("/api/ciel/objets/").json()["objets"]
        self.assertEqual([(o["nom"], o["categorie"]) for o in objets], [("ISS", "satellite")])

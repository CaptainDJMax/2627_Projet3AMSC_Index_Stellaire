"""Tests du pointage : modèles, logique, API appareil et API interface.

    python manage.py test appareil
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, transaction
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone as tz

from ciel.astro import altaz, instant_depuis, radec
from ciel.models import ObjetCeleste
from ciel.test_satellites import DossierTleTemporaire, fabriquer_tle

from . import services
from .models import Appareil, Commande


# Partie 14 : ces tests visent des planètes « maintenant », à la date du jour. Une planète proche
# du Soleil (quelques semaines par an pour chacune) ferait échouer le pointage selon le jour où on lance les
# tests : le contrôle du Soleil est coupé ici et testé à part, à dates fixes (test_securite.py).
_sans_controle_soleil = patch("appareil.securite.separation_mini", return_value=180.0)


def setUpModule():
    _sans_controle_soleil.start()


def tearDownModule():
    _sans_controle_soleil.stop()


class EcartAngulaireTests(SimpleTestCase):
    def test_cas_connus(self):
        self.assertAlmostEqual(services.ecart_angulaire((0, 0), (0, 0)), 0)
        self.assertAlmostEqual(services.ecart_angulaire((0, 0), (90, 0)), 90)
        self.assertAlmostEqual(services.ecart_angulaire((0, 0), (180, 0)), 180)
        self.assertAlmostEqual(services.ecart_angulaire((0, 0), (0, 90)), 90)
        # Au zénith, l'azimut n'a plus de sens : même direction
        self.assertAlmostEqual(services.ecart_angulaire((10, 90), (200, 90)), 0)
        # Le passage par 360° ne doit pas fausser l'écart
        self.assertAlmostEqual(services.ecart_angulaire((359, 10), (1, 10)), 2 * 0.9848, places=2)


class ModeleTests(TestCase):
    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter"
        )
        self.mars = ObjetCeleste.objects.create(
            nom="Mars", categorie="planete", identifiant_skyfield="mars barycenter"
        )

    def test_jeton_genere_et_unique(self):
        autre = Appareil.objects.create()
        self.assertGreaterEqual(len(self.appareil.jeton), 40)
        self.assertNotEqual(self.appareil.jeton, autre.jeton)

    def test_connecte_selon_la_derniere_vue(self):
        self.assertFalse(self.appareil.connecte)
        self.appareil.derniere_vue = tz.now()
        self.assertTrue(self.appareil.connecte)
        self.appareil.derniere_vue = tz.now() - timedelta(seconds=30)
        self.assertFalse(self.appareil.connecte)

    def test_une_seule_commande_active_en_base(self):
        Commande.objects.create(appareil=self.appareil, objet=self.jupiter)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Commande.objects.create(appareil=self.appareil, objet=self.mars)

    def test_definir_cible_remplace_la_precedente(self):
        services.definir_cible(self.appareil, self.jupiter)
        services.definir_cible(self.appareil, self.mars)
        self.assertEqual(self.appareil.commandes.filter(active=True).count(), 1)
        self.assertEqual(services.commande_active(self.appareil).objet, self.mars)
        self.assertEqual(self.appareil.commandes.count(), 2)  # l'historique est conservé

    def test_arreter(self):
        services.definir_cible(self.appareil, self.jupiter)
        services.arreter(self.appareil)
        self.assertIsNone(services.commande_active(self.appareil))


class ApiAppareilTests(TestCase):
    """Côté ESP32 : POST /api/appareil/sync/ avec un jeton."""

    URL = "/api/appareil/sync/"

    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter"
        )
        self.entete = {"HTTP_AUTHORIZATION": f"Bearer {self.appareil.jeton}"}

    def sync(self, corps=None, **extra):
        return self.client.post(self.URL, corps if corps is not None else {}, content_type="application/json", **extra)

    def test_jeton_obligatoire(self):
        self.assertEqual(self.sync().status_code, 401)
        self.assertEqual(self.sync(HTTP_AUTHORIZATION="Bearer faux").status_code, 401)
        self.assertEqual(self.sync(HTTP_AUTHORIZATION=self.appareil.jeton).status_code, 401)  # sans « Bearer »

    def test_get_refuse(self):
        self.assertEqual(self.client.get(self.URL, **self.entete).status_code, 405)

    def test_sync_enregistre_l_etat(self):
        corps = {"azimut": 370.5, "elevation": -12.25, "batterie": 87.4, "mode": "deplacement"}
        reponse = self.sync(corps, **self.entete)
        self.assertEqual(reponse.status_code, 200)
        self.appareil.refresh_from_db()
        self.assertAlmostEqual(self.appareil.azimut, 10.5)  # ramené dans [0, 360[
        self.assertEqual(self.appareil.elevation, -12.25)
        self.assertEqual(self.appareil.batterie, 87)
        self.assertEqual(self.appareil.mode, "deplacement")
        self.assertTrue(self.appareil.connecte)

    def test_sync_vide_est_un_simple_signe_de_vie(self):
        self.assertEqual(self.sync({}, **self.entete).status_code, 200)
        self.appareil.refresh_from_db()
        self.assertTrue(self.appareil.connecte)

    def test_sync_refuse_les_valeurs_invalides(self):
        invalides = [
            {"elevation": 120}, {"elevation": "haut"}, {"azimut": True}, {"batterie": 150},
            {"mode": "danse"}, {"azimut": float("nan")}, [1, 2, 3],
        ]
        for corps in invalides:
            with self.subTest(corps=corps):
                self.assertEqual(self.sync(corps, **self.entete).status_code, 400)
        reponse = self.client.post(self.URL, "pas du json", content_type="application/json", **self.entete)
        self.assertEqual(reponse.status_code, 400)

    def test_contrat_de_la_reponse_sans_commande(self):
        d = self.sync({}, **self.entete).json()
        self.assertEqual({"heure_serveur", "intervalle_ms", "commande"}, set(d))
        self.assertIsNone(d["commande"])

    def test_la_commande_donne_la_cible_calculee(self):
        services.definir_cible(self.appareil, self.jupiter)
        instant = instant_depuis(datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc))
        with patch("appareil.views.maintenant", return_value=instant), \
                patch("appareil.services.altaz", wraps=altaz) as calcul:
            d = self.sync({}, **self.entete).json()
        commande = d["commande"]
        self.assertEqual({"id", "mode", "objet", "cible", "trajectoire", "coordonnees", "etape"}, set(commande))  # 6.1, 8.4, 8.5
        self.assertIsNone(commande["coordonnees"])  # un objet de la base, pas un point du ciel
        self.assertIsNone(commande["etape"])  # pas une visite guidée
        self.assertEqual(commande["trajectoire"], "/api/appareil/trajectoire/")
        self.assertEqual(commande["mode"], "pointer")
        self.assertEqual(commande["objet"], {"id": self.jupiter.id, "nom": "Jupiter"})
        self.assertEqual({"azimut", "elevation", "visible"}, set(commande["cible"]))
        elevation, azimut = altaz("jupiter barycenter", 48.8566, 2.3522, 35, instant)
        self.assertAlmostEqual(commande["cible"]["azimut"], azimut, places=2)
        self.assertAlmostEqual(commande["cible"]["elevation"], elevation, places=2)
        calcul.assert_called_once()

    def test_viser_sous_l_horizon_est_permis(self):
        """Le bras est ouvert : une élévation négative est une consigne valide."""
        services.definir_cible(self.appareil, self.jupiter)
        nuit = instant_depuis(datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc))  # Jupiter couchée à Paris
        with patch("appareil.views.maintenant", return_value=nuit):
            cible = self.sync({}, **self.entete).json()["commande"]["cible"]
        self.assertLess(cible["elevation"], 0)
        self.assertFalse(cible["visible"])


CODE_TEST = "code-de-test"


@override_settings(CODE_PILOTAGE=CODE_TEST)
class ApiPointageTests(TestCase):
    """Côté interface web : état, choix d'une cible, arrêt (navigateur autorisé par le code)."""

    def setUp(self):
        cache.clear()
        self.client.post("/api/pointage/pilotage/", {"code": CODE_TEST}, content_type="application/json")
        self.appareil = Appareil.objects.create()
        self.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter"
        )
        self.mars = ObjetCeleste.objects.create(
            nom="Mars", categorie="planete", identifiant_skyfield="mars barycenter"
        )
        self.sans_id = ObjetCeleste.objects.create(nom="Amas", categorie="amas")

    def commander(self, objet_id):
        return self.client.post(
            "/api/pointage/commande/", {"objet_id": objet_id}, content_type="application/json"
        )

    def test_sans_appareil(self):
        Appareil.objects.all().delete()
        self.assertEqual(
            self.client.get("/api/pointage/").json(),
            {"appareil": None, "commande": None, "ecart_deg": None,
             "pilotage": {"autorise": True, "configure": True}},
        )
        self.assertEqual(self.commander(self.jupiter.id).status_code, 404)
        self.assertEqual(self.client.post("/api/pointage/arret/").status_code, 404)

    def test_etat_contrat(self):
        d = self.client.get("/api/pointage/").json()
        self.assertEqual({"appareil", "commande", "ecart_deg", "pilotage"}, set(d))  # pilotage : Partie 5
        self.assertEqual(
            {"nom", "connecte", "derniere_vue", "azimut", "elevation", "batterie", "mode", "ra", "dec"},
            set(d["appareil"]),
        )
        self.assertFalse(d["appareil"]["connecte"])
        self.assertIsNone(d["commande"])
        self.assertIsNone(d["appareil"]["ra"])  # position inconnue : pas de coordonnées du ciel

    def test_position_du_bras_en_coordonnees_du_ciel(self):
        """Le bras pointé sur Jupiter doit être donné aux coordonnées (ra, dec) de Jupiter."""
        self.commander(self.jupiter.id)
        cible = self.client.get("/api/pointage/").json()["commande"]["cible"]
        self.appareil.azimut, self.appareil.elevation = cible["azimut"], cible["elevation"]
        self.appareil.save()
        bras = self.client.get("/api/pointage/").json()["appareil"]
        lieu = settings.LIEU_PAR_DEFAUT
        ra, dec = radec("jupiter barycenter", lieu["latitude"], lieu["longitude"], lieu["altitude_m"])
        self.assertLess(abs((bras["ra"] - ra + 180) % 360 - 180), 0.05)
        self.assertLess(abs(bras["dec"] - dec), 0.05)

    def test_commander_puis_remplacer_puis_arreter(self):
        d = self.commander(self.jupiter.id).json()
        self.assertEqual(d["commande"]["objet"]["nom"], "Jupiter")
        self.assertEqual({"azimut", "elevation", "visible"}, set(d["commande"]["cible"]))

        d = self.commander(self.mars.id).json()
        self.assertEqual(d["commande"]["objet"]["nom"], "Mars")
        self.assertEqual(self.appareil.commandes.filter(active=True).count(), 1)

        d = self.client.post("/api/pointage/arret/").json()
        self.assertIsNone(d["commande"])

    def test_ecart_calcule_depuis_la_position_rapportee(self):
        self.assertIsNone(self.commander(self.jupiter.id).json()["ecart_deg"])  # position inconnue
        cible = self.client.get("/api/pointage/").json()["commande"]["cible"]
        self.appareil.azimut, self.appareil.elevation = cible["azimut"], cible["elevation"]
        self.appareil.save()
        self.assertAlmostEqual(self.client.get("/api/pointage/").json()["ecart_deg"], 0, places=1)

    def test_commande_invalide(self):
        self.assertEqual(self.commander(99999).status_code, 404)
        self.assertEqual(self.commander(self.sans_id.id).status_code, 404)
        for corps in ({}, {"objet_id": "1"}, {"objet_id": True}, {"objet_id": None}):
            with self.subTest(corps=corps):
                reponse = self.client.post("/api/pointage/commande/", corps, content_type="application/json")
                self.assertEqual(reponse.status_code, 400)
        self.assertEqual(self.appareil.commandes.count(), 0)

    def test_methodes(self):
        self.assertEqual(self.client.get("/api/pointage/commande/").status_code, 405)
        self.assertEqual(self.client.get("/api/pointage/arret/").status_code, 405)
        self.assertEqual(self.client.post("/api/pointage/").status_code, 405)


@override_settings(CODE_PILOTAGE=CODE_TEST)
class PilotageTests(TestCase):
    """Partie 5 : piloter le bras demande le code ; regarder, non ; l'appareil garde son jeton."""

    OUVRIR = "/api/pointage/pilotage/"

    def setUp(self):
        cache.clear()
        self.appareil = Appareil.objects.create()
        self.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter"
        )

    def code(self, code):
        return self.client.post(self.OUVRIR, {"code": code}, content_type="application/json")

    def commander(self):
        return self.client.post(
            "/api/pointage/commande/", {"objet_id": self.jupiter.id}, content_type="application/json"
        )

    def test_sans_code_on_regarde_mais_on_ne_pilote_pas(self):
        etat = self.client.get("/api/pointage/").json()
        self.assertEqual(etat["pilotage"], {"autorise": False, "configure": True})
        for reponse in (self.commander(), self.client.post("/api/pointage/arret/")):
            self.assertEqual(reponse.status_code, 403)
            self.assertTrue(reponse.json()["code_requis"])
        self.assertEqual(self.appareil.commandes.count(), 0)

    def test_bon_code_autorise_pour_30_jours(self):
        reponse = self.code(CODE_TEST)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["pilotage"], {"autorise": True, "configure": True})
        self.assertAlmostEqual(self.client.session.get_expiry_age(), 30 * 24 * 3600, delta=60)
        self.assertEqual(self.commander().status_code, 200)

    def test_espaces_autour_du_code_toleres(self):
        self.assertEqual(self.code(f"  {CODE_TEST} ").status_code, 200)

    def test_code_faux_puis_blocage(self):
        for restants in (4, 3, 2, 1):
            reponse = self.code("mauvais")
            self.assertEqual(reponse.status_code, 403)
            self.assertEqual(reponse.json()["essais_restants"], restants)
        self.assertEqual(self.code("mauvais").status_code, 429)  # 5e essai faux : bloqué
        bloque = self.code(CODE_TEST)  # même le bon code est refusé pendant le blocage
        self.assertEqual(bloque.status_code, 429)
        self.assertGreater(bloque.json()["attente_s"], 0)
        self.assertEqual(self.commander().status_code, 403)

    def test_verrouiller(self):
        self.code(CODE_TEST)
        reponse = self.client.post("/api/pointage/pilotage/fin/")
        self.assertEqual(reponse.json()["pilotage"]["autorise"], False)
        self.assertEqual(self.commander().status_code, 403)

    def test_changer_le_code_retire_les_autorisations(self):
        self.code(CODE_TEST)
        with override_settings(CODE_PILOTAGE="nouveau-code"):
            self.assertFalse(self.client.get("/api/pointage/").json()["pilotage"]["autorise"])
            self.assertEqual(self.commander().status_code, 403)

    def test_code_non_configure(self):
        with override_settings(CODE_PILOTAGE=""):
            self.assertEqual(self.code("").status_code, 503)
            self.assertEqual(self.code("nimporte").status_code, 503)
            self.assertEqual(self.client.get("/api/pointage/").json()["pilotage"]["configure"], False)
            self.assertEqual(self.commander().status_code, 403)

    def test_corps_invalide(self):
        for corps in ({}, {"code": 123456}, {"code": None}):
            with self.subTest(corps=corps):
                self.assertEqual(
                    self.client.post(self.OUVRIR, corps, content_type="application/json").status_code, 400
                )
        self.assertEqual(self.client.get(self.OUVRIR).status_code, 405)

    def test_le_code_n_est_pas_garde_en_session(self):
        self.code(CODE_TEST)
        self.assertNotIn(CODE_TEST, str(dict(self.client.session.items())))

    def test_l_appareil_n_a_pas_besoin_du_code(self):
        """Le jeton de l'appareil et le code de pilotage sont deux mécanismes séparés."""
        reponse = self.client.post(
            "/api/appareil/sync/", {}, content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.appareil.jeton}",
        )
        self.assertEqual(reponse.status_code, 200)


class TrajectoireTests(TestCase):
    """Partie 6.1 : trajectoire longue téléchargée par l'appareil (autonomie sans réseau)."""

    URL = "/api/appareil/trajectoire/"

    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.entete = {"HTTP_AUTHORIZATION": f"Bearer {self.appareil.jeton}"}
        self.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter"
        )
        self.instant = instant_depuis(datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc))

    def lire(self, **params):
        with patch("appareil.views.maintenant", return_value=self.instant):
            return self.client.get(self.URL, params, **self.entete)

    def test_jeton_obligatoire(self):
        self.assertEqual(self.client.get(self.URL).status_code, 401)
        self.assertEqual(self.client.get(self.URL, HTTP_AUTHORIZATION="Bearer faux").status_code, 401)

    def test_sans_commande(self):
        self.assertEqual(self.lire().json(), {"commande": None})

    def test_contrat_48_h_une_position_par_minute(self):
        services.definir_cible(self.appareil, self.jupiter)
        d = self.lire().json()
        self.assertEqual({"commande", "type", "debut", "pas_s", "format", "points", "tle", "lieu"}, set(d))
        self.assertEqual(d["type"], "positions")
        self.assertIsNone(d["tle"])  # 6.2 : pas un satellite
        self.assertEqual(d["lieu"], {"latitude": 48.8566, "longitude": 2.3522, "altitude_m": 35})
        self.assertEqual(d["pas_s"], 60)
        self.assertEqual(d["format"], ["azimut", "elevation"])
        self.assertEqual(d["commande"]["objet"], {"id": self.jupiter.id, "nom": "Jupiter"})
        self.assertEqual(len(d["points"]), 48 * 60 + 1)
        self.assertTrue(all(0 <= az < 360 and -90 <= el <= 90 for az, el in d["points"]))
        self.assertTrue(any(el < 0 for _, el in d["points"]))  # sous l'horizon : consigne valide
        self.assertLess(len(self.lire().content), 60_000)  # environ 45 Ko : raisonnable pour un ESP32

    def test_premier_point_egal_a_la_cible_du_moment(self):
        services.definir_cible(self.appareil, self.jupiter)
        az, el = self.lire().json()["points"][0]
        elevation, azimut = altaz("jupiter barycenter", 48.8566, 2.3522, 35, self.instant)
        self.assertAlmostEqual(az, azimut, places=1)
        self.assertAlmostEqual(el, elevation, places=1)

    def test_point_a_une_heure(self):
        services.definir_cible(self.appareil, self.jupiter)
        az, el = self.lire().json()["points"][60]
        une_heure_apres = instant_depuis(datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc))
        elevation, azimut = altaz("jupiter barycenter", 48.8566, 2.3522, 35, une_heure_apres)
        self.assertAlmostEqual(az, azimut, places=1)
        self.assertAlmostEqual(el, elevation, places=1)

    def test_duree_reglable_et_bornee(self):
        services.definir_cible(self.appareil, self.jupiter)
        self.assertEqual(len(self.lire(heures=2).json()["points"]), 2 * 60 + 1)
        self.assertEqual(len(self.lire(heures=0).json()["points"]), 1 * 60 + 1)
        self.assertEqual(len(self.lire(heures=500).json()["points"]), 48 * 60 + 1)
        self.assertEqual(self.lire(heures="abc").status_code, 400)


class LieuGpsTests(TestCase):
    """Partie 6.2 : l'appareil envoie sa position GPS ; les calculs se font pour ce lieu."""

    LYON = {"latitude": 45.764, "longitude": 4.8357, "altitude_m": 170.0}

    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.entete = {"HTTP_AUTHORIZATION": f"Bearer {self.appareil.jeton}"}
        self.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter"
        )
        self.instant = instant_depuis(datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc))

    def sync(self, corps):
        with patch("appareil.views.maintenant", return_value=self.instant):
            return self.client.post("/api/appareil/sync/", corps, content_type="application/json", **self.entete)

    def test_position_gps_enregistree(self):
        self.assertEqual(self.sync(self.LYON).status_code, 200)
        self.appareil.refresh_from_db()
        self.assertEqual((self.appareil.latitude, self.appareil.longitude, self.appareil.altitude_m),
                         (45.764, 4.8357, 170.0))
        self.assertIsNotNone(self.appareil.lieu_mis_a_jour)
        self.assertEqual(services.lieu_observation(self.appareil), self.LYON)

    def test_sans_gps_lieu_par_defaut(self):
        self.sync({"azimut": 10})
        self.appareil.refresh_from_db()
        self.assertEqual(services.lieu_observation(self.appareil), settings.LIEU_PAR_DEFAUT)

    def test_altitude_facultative(self):
        self.sync({"latitude": 45.764, "longitude": 4.8357})
        self.appareil.refresh_from_db()
        self.assertEqual(services.lieu_observation(self.appareil)["altitude_m"], 0)

    def test_valeurs_invalides(self):
        for corps in [{"latitude": 45.0}, {"longitude": 4.0}, {"latitude": 95, "longitude": 4},
                      {"latitude": 45, "longitude": 190}, {"latitude": "45", "longitude": 4},
                      {"latitude": 45, "longitude": 4, "altitude_m": 20000}]:
            with self.subTest(corps=corps):
                self.assertEqual(self.sync(corps).status_code, 400)

    def test_cible_et_trajectoire_calculees_pour_le_lieu_gps(self):
        self.sync(self.LYON)
        services.definir_cible(self.appareil, self.jupiter)
        cible = self.sync({}).json()["commande"]["cible"]
        elevation, azimut = altaz("jupiter barycenter", 45.764, 4.8357, 170, self.instant)
        self.assertAlmostEqual(cible["azimut"], azimut, places=2)
        self.assertAlmostEqual(cible["elevation"], elevation, places=2)
        with patch("appareil.views.maintenant", return_value=self.instant):
            d = self.client.get("/api/appareil/trajectoire/", **self.entete).json()
        self.assertEqual(d["lieu"], self.LYON)
        self.assertAlmostEqual(d["points"][0][0], azimut, places=1)


class LieuSecoursTests(TestCase):
    """Partie 6.4 : position partagée par le navigateur, utilisée tant que le robot n'a pas de GPS."""

    LYON = {"latitude": 45.764, "longitude": 4.8357, "altitude_m": 170.0}
    CAPE_TOWN = {"latitude": -33.9, "longitude": 18.4, "altitude_m": 10.0}

    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.jupiter = ObjetCeleste.objects.create(
            nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter"
        )

    def partager(self, lieu):
        return self.client.post("/api/ciel/lieu/", lieu, content_type="application/json")

    def test_secours_utilise_sans_gps_robot(self):
        self.assertEqual(
            services.lieu_observation(self.appareil, secours=self.CAPE_TOWN), self.CAPE_TOWN
        )

    def test_gps_robot_prioritaire_sur_le_secours(self):
        self.appareil.latitude, self.appareil.longitude, self.appareil.altitude_m = (
            self.LYON["latitude"], self.LYON["longitude"], self.LYON["altitude_m"]
        )
        self.appareil.save()
        self.assertEqual(
            services.lieu_observation(self.appareil, secours=self.CAPE_TOWN), self.LYON
        )

    def test_position_partagee_utilisee_par_le_pointage_sans_gps_robot(self):
        self.partager(self.CAPE_TOWN)
        services.definir_cible(self.appareil, self.jupiter)
        cible = self.client.get("/api/pointage/").json()["commande"]["cible"]
        elevation, azimut = altaz(
            "jupiter barycenter", self.CAPE_TOWN["latitude"], self.CAPE_TOWN["longitude"],
            self.CAPE_TOWN["altitude_m"],
        )
        self.assertAlmostEqual(cible["azimut"], azimut, places=1)
        self.assertAlmostEqual(cible["elevation"], elevation, places=1)


class TrajectoireSatelliteTests(DossierTleTemporaire, TestCase):
    """Partie 6.2 : pour l'ISS, la trajectoire porte le TLE et des points toutes les 5 s sur 6 h."""

    URL = "/api/appareil/trajectoire/"

    def setUp(self):
        super().setUp()
        self.appareil = Appareil.objects.create()
        self.entete = {"HTTP_AUTHORIZATION": f"Bearer {self.appareil.jeton}"}
        self.iss = ObjetCeleste.objects.create(nom="ISS", categorie="satellite", identifiant_skyfield="sat:25544")
        self.epoque = datetime.now(timezone.utc).replace(microsecond=0)
        self.texte = fabriquer_tle(self.epoque)
        services.definir_cible(self.appareil, self.iss)

    def lire(self, **params):
        with patch("ciel.satellites._telecharger", return_value=self.texte),                 patch("appareil.views.maintenant", return_value=instant_depuis(self.epoque)):
            return self.client.get(self.URL, params, **self.entete)

    def test_contrat(self):
        reponse = self.lire()
        d = reponse.json()
        self.assertEqual({"commande", "type", "debut", "pas_s", "format", "points", "tle", "lieu"}, set(d))
        self.assertEqual(d["type"], "positions")  # inchangé : un firmware sans SGP4 suit les points
        self.assertEqual(d["pas_s"], 5)
        self.assertEqual(len(d["points"]), 6 * 3600 // 5 + 1)
        self.assertEqual({"nom", "ligne1", "ligne2", "epoque"}, set(d["tle"]))
        self.assertEqual(d["tle"]["nom"], "ISS (ZARYA)")
        self.assertEqual((len(d["tle"]["ligne1"]), len(d["tle"]["ligne2"])), (69, 69))
        self.assertLess(len(reponse.content), 90_000)  # environ 70 Ko : raisonnable pour l'ESP32-C3

    def test_duree_bornee_a_6_h(self):
        self.assertEqual(len(self.lire(heures=2).json()["points"]), 2 * 720 + 1)
        self.assertEqual(len(self.lire(heures=48).json()["points"]), 6 * 720 + 1)

    def test_les_points_concordent_avec_le_calcul_du_robot(self):
        from appareil.management.commands.simuler_appareil import ecart_controle, instant_unix

        d = self.lire().json()
        traj = {"debut": instant_unix(d["debut"]), "pas_s": d["pas_s"], "points": d["points"],
                "tle": d["tle"], "lieu": d["lieu"]}
        self.assertLess(ecart_controle(traj), 0.05)

    def test_debut_a_la_seconde_entiere(self):
        """Le début est envoyé sans fraction de seconde : les points doivent partir de cet instant."""
        from appareil.management.commands.simuler_appareil import ecart_controle, instant_unix

        instant = instant_depuis(self.epoque + timedelta(seconds=10.6))
        with patch("ciel.satellites._telecharger", return_value=self.texte), \
                patch("appareil.views.maintenant", return_value=instant):
            d = self.client.get(self.URL, **self.entete).json()
        traj = {"debut": instant_unix(d["debut"]), "pas_s": d["pas_s"], "points": d["points"],
                "tle": d["tle"], "lieu": d["lieu"]}
        self.assertEqual(traj["debut"] % 1, 0)
        self.assertLess(ecart_controle(traj), 0.05)

    def test_sans_tle_422(self):
        with patch("ciel.satellites._telecharger", side_effect=OSError("réseau coupé")):
            reponse = self.client.get(self.URL, **self.entete)
        self.assertEqual(reponse.status_code, 422)
        self.assertIn("erreur", reponse.json())

    def test_la_sync_donne_la_cible_de_l_iss(self):
        with patch("ciel.satellites._telecharger", return_value=self.texte):
            commande = self.client.post("/api/appareil/sync/", {}, content_type="application/json",
                                        **self.entete).json()["commande"]
        self.assertEqual(commande["objet"]["nom"], "ISS")
        self.assertEqual({"azimut", "elevation", "visible"}, set(commande["cible"]))


class SimulateurTests(SimpleTestCase):
    """L'interpolation que le firmware devra reproduire (voir simuler_appareil)."""

    def test_interpolation_et_passage_par_le_nord(self):
        from appareil.management.commands.simuler_appareil import position_sur_trajectoire

        traj = {"debut": 1000.0, "pas_s": 60, "points": [[350.0, 10.0], [10.0, 20.0], [20.0, 30.0]]}
        self.assertEqual(position_sur_trajectoire(traj, 1000.0), {"azimut": 350.0, "elevation": 10.0})
        milieu = position_sur_trajectoire(traj, 1030.0)  # 350° -> 10° par le nord, pas par le sud
        self.assertAlmostEqual(milieu["azimut"], 0.0)
        self.assertAlmostEqual(milieu["elevation"], 15.0)
        self.assertIsNone(position_sur_trajectoire(traj, 999.0))  # avant le début
        self.assertEqual(position_sur_trajectoire(traj, 1120.0), {"azimut": 20.0, "elevation": 30.0})  # dernier point
        self.assertIsNone(position_sur_trajectoire(traj, 1121.0))  # après la fin

    def test_suivi_sgp4_et_retelechargement(self):
        from appareil.management.commands.simuler_appareil import a_retelecharger, consigne_de

        from ciel import satellites

        texte = fabriquer_tle(datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc))
        _, l1, l2 = satellites.lire_tle(texte, 25544)
        debut = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc).timestamp()
        traj = {"debut": debut, "pas_s": 5, "points": [[0.0, 0.0]] * 4321,
                "tle": {"ligne1": l1, "ligne2": l2},
                "lieu": {"latitude": 48.8566, "longitude": 2.3522, "altitude_m": 35}}
        # Avec le TLE, la consigne vient de SGP4 (pas des points factices), jusqu'à 48 h
        self.assertNotEqual(consigne_de(traj, debut + 100), {"azimut": 0.0, "elevation": 0.0})
        self.assertIsNotNone(consigne_de(traj, debut + 47 * 3600))
        self.assertIsNone(consigne_de(traj, debut + 49 * 3600))
        # Sans SGP4 : les points
        self.assertEqual(consigne_de(traj, debut + 100, avec_sgp4=False), {"azimut": 0.0, "elevation": 0.0})
        # Retéléchargement quand il reste moins d'une heure de points
        self.assertFalse(a_retelecharger(traj, debut + 4 * 3600))
        self.assertTrue(a_retelecharger(traj, debut + 5.5 * 3600))


@override_settings(CODE_PILOTAGE=CODE_TEST)
class CiblePersonnaliseeTests(TestCase):
    """Partie 8.4 (F18) : pointer un point fixe du ciel, même sous l'horizon."""

    BETELGEUSE = {"ra": 88.7929, "dec": 7.4071}

    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.entete = {"HTTP_AUTHORIZATION": f"Bearer {self.appareil.jeton}"}
        self.client.post("/api/pointage/pilotage/", {"code": CODE_TEST}, content_type="application/json")
        self.instant = instant_depuis(datetime(2026, 10, 12, 23, 0, tzinfo=timezone.utc))

    def commander(self, corps):
        return self.client.post("/api/pointage/commande/", corps, content_type="application/json")

    def test_commande_d_un_point(self):
        d = self.commander({**self.BETELGEUSE, "nom": "Mon point"}).json()
        self.assertEqual(d["commande"]["objet"], {"id": None, "nom": "Mon point"})
        self.assertEqual(d["commande"]["coordonnees"], self.BETELGEUSE)
        c = services.commande_active(self.appareil)
        self.assertIsNone(c.objet)
        self.assertEqual(c.identifiant, "radec:88.7929,7.4071")

    def test_nom_par_defaut_et_ra_ramenee(self):
        d = self.commander({"ra": -10, "dec": -45}).json()
        self.assertEqual(d["commande"]["objet"]["nom"], "Point du ciel")
        self.assertEqual(d["commande"]["coordonnees"], {"ra": 350.0, "dec": -45.0})

    def test_valeurs_invalides(self):
        for corps in [{"ra": 10}, {"dec": 10}, {"ra": "10", "dec": 5}, {"ra": 10, "dec": 95},
                      {"ra": 10, "dec": 5, "nom": "x" * 61}, {"ra": True, "dec": 5}, [1, 2]]:
            with self.subTest(corps=corps):
                self.assertEqual(self.commander(corps).status_code, 400)

    def test_code_de_pilotage_exige(self):
        self.client.post("/api/pointage/pilotage/fin/")
        self.assertEqual(self.commander(self.BETELGEUSE).status_code, 403)

    def test_le_bras_vise_le_point_comme_une_etoile(self):
        """Un point aux coordonnées de Bételgeuse se calcule comme Bételgeuse."""
        self.commander(self.BETELGEUSE)
        with patch("appareil.views.maintenant", return_value=self.instant):
            cible = self.client.post("/api/appareil/sync/", {}, content_type="application/json", **self.entete).json()["commande"]["cible"]
        elevation, azimut = altaz("hip:27989", 48.8566, 2.3522, 35, self.instant)
        self.assertAlmostEqual(cible["azimut"], azimut, delta=0.02)
        self.assertAlmostEqual(cible["elevation"], elevation, delta=0.02)

    def test_trajectoire_d_un_point_sous_l_horizon(self):
        self.commander({"ra": 100.0, "dec": -80.0})  # près du pôle Sud : jamais levé à Paris
        with patch("appareil.views.maintenant", return_value=self.instant):
            d = self.client.get("/api/appareil/trajectoire/", **self.entete).json()
        self.assertEqual(d["commande"]["objet"]["id"], None)
        self.assertEqual(d["pas_s"], 60)
        self.assertIsNone(d["tle"])
        self.assertTrue(all(el < 0 for _, el in d["points"]))  # le bras pointe à travers la Terre

    def test_remplacer_un_point_par_un_objet(self):
        jupiter = ObjetCeleste.objects.create(nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter")
        self.commander(self.BETELGEUSE)
        d = self.commander({"objet_id": jupiter.id}).json()
        self.assertEqual(d["commande"]["objet"], {"id": jupiter.id, "nom": "Jupiter"})
        self.assertIsNone(d["commande"]["coordonnees"])
        self.assertEqual(self.appareil.commandes.filter(active=True).count(), 1)

    def test_ni_objet_ni_coordonnees_refuse_en_base(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Commande.objects.create(appareil=self.appareil)


@override_settings(CODE_PILOTAGE=CODE_TEST)
class VisiteGuideeTests(TestCase):
    """Partie 8.5 (F22) : enchaîner plusieurs cibles avec des horaires, même hors ligne."""

    URL = "/api/pointage/visite/"

    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.entete = {"HTTP_AUTHORIZATION": f"Bearer {self.appareil.jeton}"}
        self.client.post("/api/pointage/pilotage/", {"code": CODE_TEST}, content_type="application/json")
        self.jupiter = ObjetCeleste.objects.create(nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter")
        self.saturne = ObjetCeleste.objects.create(nom="Saturne", categorie="planete", identifiant_skyfield="saturn barycenter")
        self.debut = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)

    def lancer(self, corps):
        with patch("appareil.views.timezone.now", return_value=self.debut - timedelta(minutes=1)):
            return self.client.post(self.URL, corps, content_type="application/json")

    def visite(self):
        return self.lancer({"debut": "2026-10-12T20:00:00Z", "etapes": [
            {"objet_id": self.jupiter.id, "duree_min": 10},
            {"ra": 88.7929, "dec": 7.4071, "nom": "Bételgeuse à la main", "duree_min": 5},
            {"objet_id": self.saturne.id, "duree_min": 15},
        ]})

    def sync_a(self, quand):
        with patch("appareil.views.maintenant", return_value=instant_depuis(quand)):
            return self.client.post("/api/appareil/sync/", {}, content_type="application/json", **self.entete).json()["commande"]

    def test_etat_de_la_visite(self):
        d = self.visite().json()
        prog = d["commande"]["programme"]
        self.assertEqual(prog["debut"], "2026-10-12T20:00:00Z")
        self.assertEqual([e["nom"] for e in prog["etapes"]], ["Jupiter", "Bételgeuse à la main", "Saturne"])
        self.assertEqual([e["fin"] for e in prog["etapes"]], ["2026-10-12T20:10:00Z", "2026-10-12T20:15:00Z", None])
        self.assertEqual(prog["etapes"][1]["coordonnees"], {"ra": 88.7929, "dec": 7.4071})

    def test_la_cible_change_avec_l_heure(self):
        self.visite()
        avant = self.sync_a(self.debut - timedelta(minutes=30))  # pas encore commencée : 1re étape
        e1 = self.sync_a(self.debut + timedelta(minutes=3))
        e2 = self.sync_a(self.debut + timedelta(minutes=12))
        e3 = self.sync_a(self.debut + timedelta(hours=5))  # finie : reste sur la dernière
        self.assertEqual(avant["objet"]["nom"], "Jupiter")
        self.assertEqual((e1["objet"], e1["etape"]), ({"id": self.jupiter.id, "nom": "Jupiter"},
                                                      {"numero": 1, "total": 3, "fin": "2026-10-12T20:10:00Z"}))
        self.assertEqual((e2["objet"]["id"], e2["coordonnees"], e2["etape"]["numero"]), (None, {"ra": 88.7929, "dec": 7.4071}, 2))
        self.assertEqual((e3["objet"]["nom"], e3["etape"]), ("Saturne", {"numero": 3, "total": 3, "fin": None}))
        el, az = altaz("hip:27989", 48.8566, 2.3522, 35, instant_depuis(self.debut + timedelta(minutes=12)))
        self.assertAlmostEqual(e2["cible"]["azimut"], az, delta=0.02)
        # Même commande du début à la fin : le robot ne retélécharge pas sa trajectoire
        self.assertEqual(len({c["id"] for c in (avant, e1, e2, e3)}), 1)

    def test_trajectoire_qui_enchaine_les_etapes(self):
        """Le robot suit la visite seul, sans réseau : ses points changent de cible aux bonnes heures."""
        self.visite()
        with patch("appareil.views.maintenant", return_value=instant_depuis(self.debut)):
            d = self.client.get("/api/appareil/trajectoire/?heures=1", **self.entete).json()
        self.assertEqual(d["pas_s"], 60)
        for minute, ident in [(5, "jupiter barycenter"), (12, "hip:27989"), (40, "saturn barycenter")]:
            el, az = altaz(ident, 48.8566, 2.3522, 35, instant_depuis(self.debut + timedelta(minutes=minute)))
            with self.subTest(minute=minute):
                self.assertAlmostEqual(d["points"][minute][0], az, delta=0.05)
                self.assertAlmostEqual(d["points"][minute][1], el, delta=0.05)

    def test_refus(self):
        iss = ObjetCeleste.objects.create(nom="ISS", categorie="satellite", identifiant_skyfield="sat:25544")
        mauvais = [
            {"etapes": []},
            {"etapes": [{"objet_id": self.jupiter.id}]},  # sans durée
            {"etapes": [{"objet_id": self.jupiter.id, "duree_min": 0}]},
            {"etapes": [{"objet_id": self.jupiter.id, "duree_min": 241}]},
            {"etapes": [{"objet_id": self.jupiter.id, "duree_min": 5}] * 21},
            {"etapes": [{"objet_id": iss.id, "duree_min": 5}]},  # satellite : non
            {"debut": "2026-10-20T20:00:00Z", "etapes": [{"objet_id": self.jupiter.id, "duree_min": 5}]},  # trop tard
            {"debut": "2026-10-12T20:00:00", "etapes": [{"objet_id": self.jupiter.id, "duree_min": 5}]},  # sans fuseau
        ]
        for corps in mauvais:
            with self.subTest(corps=str(corps)[:60]):
                self.assertEqual(self.lancer(corps).status_code, 400)
        self.assertEqual(self.lancer({"etapes": [{"objet_id": 9999, "duree_min": 5}]}).status_code, 404)

    def test_debut_maintenant_par_defaut_et_code_exige(self):
        d = self.lancer({"etapes": [{"objet_id": self.saturne.id, "duree_min": 20}]}).json()
        self.assertEqual(d["commande"]["programme"]["etape"], 1)
        self.client.post("/api/pointage/pilotage/fin/")
        self.assertEqual(self.lancer({"etapes": [{"objet_id": self.saturne.id, "duree_min": 20}]}).status_code, 403)

    def test_une_commande_simple_remplace_la_visite(self):
        self.visite()
        d = self.client.post("/api/pointage/commande/", {"objet_id": self.jupiter.id}, content_type="application/json").json()
        self.assertIsNone(d["commande"]["programme"])
        self.assertEqual(self.appareil.commandes.filter(active=True).count(), 1)


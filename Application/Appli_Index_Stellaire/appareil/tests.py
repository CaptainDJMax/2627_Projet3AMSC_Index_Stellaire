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

from . import services
from .models import Appareil, Commande


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
        self.assertEqual({"id", "mode", "objet", "cible", "trajectoire"}, set(commande))  # trajectoire : 6.1
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
        self.assertEqual({"commande", "type", "debut", "pas_s", "format", "points"}, set(d))
        self.assertEqual(d["type"], "positions")
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

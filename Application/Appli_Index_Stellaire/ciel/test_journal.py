"""Partie 9 : journal d'observation (observations notées + pointages du bras).

    python manage.py test ciel
"""

import csv
import io
from datetime import datetime, timedelta, timezone as tz
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from appareil import services
from appareil.models import Appareil, Commande

from .models import ObjetCeleste, Observation

CODE = "code-journal"


@override_settings(CODE_PILOTAGE=CODE)
class JournalTests(TestCase):
    def setUp(self):
        self.saturne = ObjetCeleste.objects.create(nom="Saturne", categorie="planete", identifiant_skyfield="saturn barycenter")
        self.lune = ObjetCeleste.objects.create(nom="Lune", categorie="lune", identifiant_skyfield="moon")
        self.client.post("/api/pointage/pilotage/", {"code": CODE}, content_type="application/json")

    def noter(self, corps):
        return self.client.post("/api/ciel/journal/noter/", corps, content_type="application/json")

    def test_noter_et_relire(self):
        r = self.noter({"objet_id": self.saturne.id, "ciel": "clair", "instrument": "jumelles", "note": "Anneaux visibles ?"})
        self.assertEqual(r.status_code, 201)
        o = r.json()["observation"]
        self.assertEqual({"id", "quand", "nom", "objet_id", "coordonnees", "lieu", "ciel", "instrument", "note", "direction"}, set(o))
        self.assertEqual({"azimut", "elevation"}, set(o["direction"]))  # pour revoir l'observation sur la carte
        self.assertEqual((o["nom"], o["ciel"], o["instrument"]), ("Saturne", "clair", "jumelles"))
        self.assertEqual(o["lieu"], {"latitude": 48.8566, "longitude": 2.3522})  # lieu courant : le lieu par défaut ici
        d = self.client.get("/api/ciel/journal/").json()
        self.assertEqual({"observations", "pointages"}, set(d))
        self.assertEqual([x["note"] for x in d["observations"]], ["Anneaux visibles ?"])

    def test_point_du_ciel_et_date_passee(self):
        hier = (timezone.now() - timedelta(days=1)).replace(microsecond=0)
        o = self.noter({"ra": 88.79, "dec": 7.41, "nom": "Bételgeuse au jugé", "quand": hier.isoformat()}).json()["observation"]
        self.assertEqual(o["coordonnees"], {"ra": 88.79, "dec": 7.41})
        self.assertIsNone(o["objet_id"])
        self.assertEqual(datetime.fromisoformat(o["quand"].replace("Z", "+00:00")), hier)
        self.assertEqual((o["ciel"], o["instrument"]), ("inconnu", "oeil"))  # valeurs par défaut

    def test_refus(self):
        demain = (timezone.now() + timedelta(days=1)).isoformat()
        for corps in [{}, {"objet_id": "1"}, {"ra": 10}, {"objet_id": self.saturne.id, "ciel": "orage"},
                      {"objet_id": self.saturne.id, "instrument": "radar"}, {"objet_id": self.saturne.id, "note": "x" * 2001},
                      {"objet_id": self.saturne.id, "quand": demain}, {"objet_id": self.saturne.id, "quand": "2026-10-12T20:00:00"}]:
            with self.subTest(corps=str(corps)[:50]):
                self.assertEqual(self.noter(corps).status_code, 400)
        self.assertEqual(self.noter({"objet_id": 9999}).status_code, 404)

    def test_ecrire_demande_le_code_lire_non(self):
        self.noter({"objet_id": self.saturne.id})
        self.client.post("/api/pointage/pilotage/fin/")
        self.assertEqual(self.noter({"objet_id": self.saturne.id}).status_code, 403)
        o = Observation.objects.get()
        self.assertEqual(self.client.post(f"/api/ciel/journal/{o.id}/effacer/").status_code, 403)
        self.assertEqual(self.client.get("/api/ciel/journal/").status_code, 200)

    def test_effacer(self):
        o = self.noter({"objet_id": self.saturne.id}).json()["observation"]
        self.assertEqual(self.client.post(f"/api/ciel/journal/{o['id']}/effacer/").json(), {"efface": o["id"]})
        self.assertEqual(self.client.post(f"/api/ciel/journal/{o['id']}/effacer/").status_code, 404)

    def test_filtre_par_astre(self):
        self.noter({"objet_id": self.saturne.id})
        self.noter({"objet_id": self.lune.id})
        d = self.client.get("/api/ciel/journal/", {"objet": self.lune.id}).json()
        self.assertEqual([o["nom"] for o in d["observations"]], ["Lune"])
        self.assertEqual(self.client.get("/api/ciel/journal/", {"objet": "x"}).status_code, 400)

    def test_l_astre_efface_garde_son_nom(self):
        self.noter({"objet_id": self.saturne.id})
        self.saturne.delete()
        o = self.client.get("/api/ciel/journal/").json()["observations"][0]
        self.assertEqual((o["nom"], o["objet_id"]), ("Saturne", None))


class PointagesDuJournalTests(TestCase):
    def setUp(self):
        self.appareil = Appareil.objects.create()
        self.saturne = ObjetCeleste.objects.create(nom="Saturne", categorie="planete", identifiant_skyfield="saturn barycenter")
        self.lune = ObjetCeleste.objects.create(nom="Lune", categorie="lune", identifiant_skyfield="moon")

    def commande_a(self, quand, fonction, *args):
        with patch("django.utils.timezone.now", return_value=quand):
            c = fonction(self.appareil, *args)
        Commande.objects.filter(pk=c.pk).update(cree_le=quand)
        return c

    def test_pointages_et_visite(self):
        t0 = timezone.now() - timedelta(hours=3)
        self.commande_a(t0, services.definir_cible, self.saturne)
        self.commande_a(t0 + timedelta(minutes=30), services.definir_point, 88.79, 7.41, "Mon point")
        self.commande_a(t0 + timedelta(hours=1), services.definir_visite,
                        [{"objet": self.lune, "duree_s": 600}, {"objet": self.saturne, "duree_s": 600}],
                        t0 + timedelta(hours=1))
        d = self.client.get("/api/ciel/journal/").json()["pointages"]
        self.assertEqual([p["nom"] for p in d], ["Saturne", "Lune", "Mon point", "Saturne"])  # du plus récent au plus ancien
        self.assertEqual([p["visite"] for p in d], [True, True, False, False])
        self.assertEqual(d[2]["coordonnees"], {"ra": 88.79, "dec": 7.41})
        self.assertEqual(d[3]["fin"], d[2]["quand"])  # le pointage de Saturne finit quand le point le remplace
        self.assertIsNone(d[0]["fin"])  # dernière étape : elle dure
        self.assertTrue(all({"azimut", "elevation"} == set(p["direction"]) for p in d))
        filtre = self.client.get("/api/ciel/journal/", {"objet": self.saturne.id}).json()["pointages"]
        self.assertEqual(len(filtre), 2)

    def test_visite_interrompue(self):
        t0 = timezone.now() - timedelta(hours=3)
        self.commande_a(t0, services.definir_visite,
                        [{"objet": self.lune, "duree_s": 600}, {"objet": self.saturne, "duree_s": 600}], t0)
        self.commande_a(t0 + timedelta(minutes=5), services.definir_cible, self.saturne)  # avant la 2e étape
        d = self.client.get("/api/ciel/journal/").json()["pointages"]
        self.assertEqual([p["nom"] for p in d], ["Saturne", "Lune"])  # la 2e étape n'a jamais eu lieu
        self.assertEqual(d[1]["fin"], d[0]["quand"])


@override_settings(CODE_PILOTAGE=CODE)
class ExportTests(TestCase):
    def test_csv_tableur(self):
        saturne = ObjetCeleste.objects.create(nom="Saturne", categorie="planete", identifiant_skyfield="saturn barycenter")
        Observation.objects.create(quand=datetime(2026, 10, 12, 21, 30, tzinfo=tz.utc), objet=saturne, nom="Saturne",
                                   latitude=48.85661, longitude=2.35222, ciel="clair", instrument="oeil",
                                   note="=HYPERLINK(\"http://x\") ; très beau")
        r = self.client.get("/api/ciel/journal/export.csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", r["Content-Disposition"])
        texte = r.content.decode("utf-8")
        self.assertTrue(texte.startswith("﻿"))
        lignes = list(csv.reader(io.StringIO(texte.lstrip("﻿")), delimiter=";"))
        self.assertEqual(lignes[0][0], "date (UTC)")
        self.assertEqual(lignes[1][:2], ["2026-10-12T21:30:00Z", "Saturne"])
        self.assertEqual(lignes[1][6:8], ["Ciel clair", "À l'œil nu"])
        self.assertTrue(lignes[1][8].startswith("'="))  # pas de formule exécutée par le tableur

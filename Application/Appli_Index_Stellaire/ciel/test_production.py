"""Partie 14 : réglages de la machine (config_locale.py) et sauvegarde de la base.

    python manage.py test ciel.test_production
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase

from index_stellaire import config_locale as cl

from .models import ObjetCeleste


class ConfigLocaleTests(SimpleTestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        environ = {k: v for k, v in os.environ.items() if not k.startswith("INDEX_STELLAIRE_")}
        patcher = patch.dict(os.environ, environ, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ecrire(self, contenu):
        (self.dossier / "config_locale.json").write_text(contenu, encoding="utf-8")

    def test_sans_fichier_mode_developpement(self):
        self.assertEqual(cl.lire_config(self.dossier), {})

    def test_fichier_valide(self):
        self.ecrire(json.dumps({"production": True, "hotes": ["192.168.1.42"]}))
        self.assertEqual(cl.lire_config(self.dossier), {"production": True, "hotes": ["192.168.1.42"]})

    def test_fichier_invalide_refuse(self):
        for contenu in ['{"production": "oui"}', '{"prodution": true}', '{"hotes": "192.168.1.42"}', "[1]", "{"]:
            self.ecrire(contenu)
            with self.assertRaises(cl.ConfigInvalide, msg=contenu):
                cl.lire_config(self.dossier)

    def test_variables_d_environnement_prioritaires(self):
        self.ecrire(json.dumps({"production": True}))
        with patch.dict(os.environ, {"INDEX_STELLAIRE_PRODUCTION": "0", "INDEX_STELLAIRE_HOTES": "a.local, b.local"}):
            self.assertEqual(cl.lire_config(self.dossier), {"production": False, "hotes": ["a.local", "b.local"]})

    def test_cle_secrete_creee_une_fois(self):
        cle = cl.cle_secrete(self.dossier)
        self.assertGreaterEqual(len(cle), 50)
        self.assertTrue((self.dossier / "cle_secrete.txt").is_file())
        self.assertEqual(cl.cle_secrete(self.dossier), cle)  # relue, pas recréée
        with patch.dict(os.environ, {"INDEX_STELLAIRE_CLE": "x" * 60}):
            self.assertEqual(cl.cle_secrete(self.dossier), "x" * 60)

    def test_hotes_autorises(self):
        with patch.object(cl, "ip_locale", return_value="192.168.1.7"):
            hotes = cl.hotes_autorises({"hotes": ["mon-pc.local", "localhost"]})
        self.assertEqual(hotes, ["localhost", "127.0.0.1", "mon-pc.local", "192.168.1.7"])


class SauvegardeTests(TransactionTestCase):  # pas de transaction ouverte : comme en vrai
    def test_sauvegarde_et_rotation(self):
        ObjetCeleste.objects.create(nom="Jupiter", categorie="planete", identifiant_skyfield="jupiter barycenter")
        dossier = Path(tempfile.mkdtemp())
        for i in range(3):
            (dossier / f"db-2020-01-0{i + 1}_00-00-00.sqlite3").write_bytes(b"ancienne")
        call_command("sauvegarder_base", dossier=str(dossier), garder=2, stdout=open(os.devnull, "w"))
        fichiers = sorted(dossier.glob("db-*.sqlite3"))
        self.assertEqual(len(fichiers), 2)  # la plus récente ancienne + la nouvelle
        nouvelle = fichiers[-1]
        with sqlite3.connect(nouvelle) as base:
            noms = [r[0] for r in base.execute("SELECT nom FROM ciel_objetceleste")]
        self.assertEqual(noms, ["Jupiter"])

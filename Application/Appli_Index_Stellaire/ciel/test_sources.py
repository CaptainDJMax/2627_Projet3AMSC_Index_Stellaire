"""Partie 8.3 : sources externes en temps réel (aurores, comètes). Aucun accès réseau : les
réponses du NOAA, de COBS et du Minor Planet Center sont simulées.

Référence : la comète C/2023 A3 (Tsuchinshan-ATLAS) était visible à l'œil nu, basse à l'ouest
après le coucher du Soleil, mi-octobre 2024 en France.

    python manage.py test ciel
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from . import astro, sources_externes

PARIS = (48.8566, 2.3522, 35)


def instant(*args):
    return astro.instant_depuis(datetime(*args, tzinfo=timezone.utc))


def ligne_mpc(designation, annee, mois, jour, q, e, w, noeud, i):
    """Une ligne au format CometEls.txt du Minor Planet Center (colonnes fixes)."""
    l = [" "] * 170

    def placer(debut, texte):
        l[debut:debut + len(texte)] = list(texte)

    placer(14, f"{annee:4d}")
    placer(19, f"{mois:02d}")
    placer(22, f"{jour:7.4f}")
    placer(30, f"{q:9.6f}")
    placer(41, f"{e:8.6f}")
    placer(51, f"{w:8.4f}")
    placer(61, f"{noeud:8.4f}")
    placer(71, f"{i:8.4f}")
    placer(81, "20241001")
    placer(91, " 7.0")
    placer(96, " 4.0")
    placer(102, designation)
    placer(159, "MPEC 2024")
    return "".join(l).rstrip()


# Éléments approchés de Tsuchinshan-ATLAS (périhélie le 27 septembre 2024)
ORBITES = "\n".join([
    ligne_mpc("C/2023 A3 (Tsuchinshan-ATLAS)", 2024, 9, 27.7405, 0.391435, 1.000091, 308.4925, 21.5596, 139.1109),
    ligne_mpc("12P/Pons-Brooks", 2024, 4, 21.1427, 0.780813, 0.954627, 199.0247, 255.8541, 74.1912),
]) + "\n"

COBS = json.dumps({"objects": [
    {"id": 1, "type": "C", "name": "C/2023 A3", "fullname": "C/2023 A3 (Tsuchinshan-ATLAS)", "current_mag": "3.5"},
    {"id": 2, "type": "P", "name": "12P", "fullname": "12P/Pons-Brooks", "current_mag": 11.2},
    {"id": 3, "type": "C", "name": "C/2099 Z9", "fullname": "C/2099 Z9 (Inconnue)", "current_mag": "5"},
], "info": {}, "signature": {"version": "1.3"}})


def kp_noaa(lignes, forme="listes"):
    if forme == "listes":
        return json.dumps([["time_tag", "kp", "observed", "noaa_scale"]] + [[t, f"{k:.2f}", o, None] for t, k, o in lignes])
    return json.dumps([{"time_tag": t.replace(" ", "T"), "kp": k, "observed": o} for t, k, o in lignes])


class AvecDossierVide:
    def setUp(self):
        super().setUp()
        self._dossier = tempfile.TemporaryDirectory()
        self._reglage = override_settings(DOSSIER_SOURCES_EXTERNES=self._dossier.name)
        self._reglage.enable()
        cache.clear()

    def tearDown(self):
        self._reglage.disable()
        self._dossier.cleanup()
        cache.clear()
        super().tearDown()

    def reponses(self, **par_cle):
        """Simule le réseau : {cle de SOURCES: texte ou exception}."""
        urls = {sources_externes.SOURCES[c]["url"]: v for c, v in par_cle.items()}

        def faux(url):
            v = urls.get(url, OSError("pas de réseau"))
            if isinstance(v, Exception):
                raise v
            return v
        return patch("ciel.sources_externes._telecharger", side_effect=faux)


class CacheTests(AvecDossierVide, SimpleTestCase):
    def test_copie_locale_puis_rafraichissement(self):
        texte = kp_noaa([("2026-10-30 21:00:00", 3, "predicted")])
        with self.reponses(aurores=texte) as reseau:
            self.assertEqual(sources_externes.lire_source("aurores", sources_externes.lire_kp)[1], "ok")
            self.assertEqual(sources_externes.lire_source("aurores", sources_externes.lire_kp)[1], "ok")
        reseau.assert_called_once()  # copie fraîche : pas de second téléchargement

    def test_sans_reseau_copie_locale_puis_pas_de_nouvel_essai(self):
        texte = kp_noaa([("2026-10-30 21:00:00", 3, "predicted")])
        with self.reponses(aurores=texte):
            sources_externes.lire_source("aurores", sources_externes.lire_kp)
        fichier = os.path.join(self._dossier.name, "aurores.txt")
        vieux = time.time() - 5 * 3600  # plus de 3 h : à rafraîchir, moins de 2 jours : utilisable
        os.utime(fichier, (vieux, vieux))
        with self.reponses() as reseau:
            t1, etat1, age1 = sources_externes.lire_source("aurores", sources_externes.lire_kp)
            t2, etat2, _ = sources_externes.lire_source("aurores", sources_externes.lire_kp)
        self.assertEqual((t1, etat1, etat2), (texte, "cache", "cache"))
        self.assertAlmostEqual(age1, 5 * 3600, delta=60)
        reseau.assert_called_once()  # après un échec, pas de nouvel essai avant 30 min

    def test_reponse_invalide_ignoree(self):
        with self.reponses(aurores="<html>maintenance</html>"):
            self.assertEqual(sources_externes.lire_source("aurores", sources_externes.lire_kp), (None, "indisponible", None))


class AuroresTests(AvecDossierVide, SimpleTestCase):
    def test_seuil_selon_le_lieu(self):
        paris = sources_externes.kp_necessaire(48.86, 2.35)
        stockholm = sources_externes.kp_necessaire(59.33, 18.07)
        tromso = sources_externes.kp_necessaire(69.65, 18.96)
        self.assertTrue(7 <= paris <= 8.5)  # en France, il faut une forte tempête (Kp 7 à 9)
        self.assertTrue(4 <= stockholm <= 6)
        self.assertLess(tromso, 1)  # sous l'ovale auroral : presque chaque nuit claire

    def test_deux_formes_de_reponse(self):
        lignes = [("2026-10-30 21:00:00", 8.0, "predicted"), ("2026-10-31 00:00:00", 2.0, "predicted")]
        for forme in ("listes", "objets"):
            with self.subTest(forme=forme):
                kp = sources_externes.lire_kp(kp_noaa(lignes, forme))
                self.assertEqual(kp[0], (datetime(2026, 10, 30, 21, tzinfo=timezone.utc), 8.0, True))

    def test_aurore_annoncee_a_paris_seulement_si_kp_fort_et_de_nuit(self):
        texte = kp_noaa([
            ("2026-10-30 12:00:00", 9.0, "predicted"),  # en plein jour : rien
            ("2026-10-30 21:00:00", 8.0, "predicted"),  # de nuit, Kp 8 : oui
            ("2026-10-31 21:00:00", 5.0, "predicted"),  # trop faible pour Paris
        ])
        with self.reponses(aurores=texte):
            evs, statut = sources_externes.aurores(*PARIS, instant(2026, 10, 29), instant(2026, 11, 2))
        self.assertEqual(statut["etat"], "ok")
        self.assertEqual(len(evs), 1)
        e = evs[0]
        self.assertEqual(e["titre"], "Aurore boréale possible (Kp 8 prévu)")
        self.assertEqual(e["direction"]["azimut"], 0.0)  # vers le nord
        self.assertEqual(e["source"], "NOAA SWPC")
        self.assertTrue(e["important"])

    def test_sans_source(self):
        with self.reponses():
            evs, statut = sources_externes.aurores(*PARIS, instant(2026, 10, 29), instant(2026, 11, 2))
        self.assertEqual((evs, statut["etat"]), ([], "indisponible"))


class CometesTests(AvecDossierVide, SimpleTestCase):
    def test_tsuchinshan_atlas_octobre_2024(self):
        with self.reponses(cometes=COBS, orbites=ORBITES):
            evs, statuts = sources_externes.cometes(*PARIS, instant(2024, 10, 13, 12), instant(2024, 10, 20))
        self.assertEqual([s["nom"] for s in statuts], ["COBS", "Minor Planet Center"])
        # 12P trop faible (11,2) ; C/2099 Z9 sans orbite connue : ignorées
        self.assertEqual(len(evs), 1)
        e = evs[0]
        self.assertTrue(e["titre"].startswith("Comète C/2023 A3 (Tsuchinshan-ATLAS)"))
        self.assertEqual(e["magnitude"], 3.5)
        self.assertTrue(e["important"])
        self.assertIn("COBS", e["source"])
        self.assertTrue(225 <= e["direction"]["azimut"] <= 300)  # à l'ouest
        heure = datetime.fromisoformat(e["instant"].replace("Z", "+00:00"))
        # Le premier soir où elle monte à 10° dans un ciel assez noir (Soleil à -12°)
        self.assertTrue("2024-10-13" <= heure.date().isoformat() <= "2024-10-16")
        self.assertTrue(17 <= heure.hour <= 20)  # le soir (UTC)

    def test_rien_sans_orbites(self):
        with self.reponses(cometes=COBS):
            evs, statuts = sources_externes.cometes(*PARIS, instant(2024, 10, 13, 12), instant(2024, 10, 20))
        self.assertEqual(evs, [])
        self.assertEqual(statuts[1]["etat"], "indisponible")

    def test_ensemble_ne_leve_jamais(self):
        with self.reponses(cometes="{pas du json"):
            evs, statuts = sources_externes.evenements_externes(*PARIS, instant(2026, 10, 29), instant(2026, 11, 5))
        self.assertEqual(evs, [])
        self.assertEqual({s["nom"] for s in statuts}, {"NOAA SWPC", "COBS"})

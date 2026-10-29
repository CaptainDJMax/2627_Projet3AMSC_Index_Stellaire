"""Partie 8.3 : événements qu'on ne peut pas calculer à l'avance, pris à des sources en temps réel.

Tout ce qui est prévisible (Lune, planètes, éclipses, étoiles filantes, ISS...) est calculé par
nous, pour le lieu exact (`evenements.py`). Il reste deux choses imprévisibles :

- **Aurores** (polaires) : elles dépendent de l'activité du Soleil. Source : prévision de l'indice
  Kp sur 3 jours du NOAA Space Weather Prediction Center (service public américain, données
  libres). Visibles de France seulement lors de fortes tempêtes (Kp 7 à 9, comme en mai 2024).
- **Comètes brillantes** : on ne les connaît que quelques mois à l'avance et leur éclat est
  incertain. Sources : éclat mesuré par les observateurs (COBS, Comet Observation Database,
  licence CC BY-NC-SA 4.0, mention obligatoire) et orbite (Minor Planet Center).

Règles : chaque source est gardée en copie locale (donnees_skyfield/externes/, ignoré par Git) ;
sans réseau, on utilise la copie tant qu'elle n'est pas trop vieille ; après un échec, on ne
réessaie pas avant 30 min (la page ne doit jamais attendre un serveur injoignable). Une source en
panne n'empêche jamais d'afficher les autres événements.
"""

import io
import json
import math
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.cache import cache
from skyfield.api import wgs84

from . import astro

DELAI_APRES_ECHEC_S = 30 * 60
DELAI_RESEAU_S = 6

SOURCES = {
    "aurores": {
        "nom": "NOAA SWPC",
        "url": "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json",
        "page": "https://www.swpc.noaa.gov/products/planetary-k-index",
        "licence": "Données publiques (NOAA)",
        "rafraichir_s": 3 * 3600,
        "garder_s": 2 * 86400,  # une prévision de plus de 2 jours n'a plus de sens
    },
    "cometes": {
        "nom": "COBS",
        "url": "https://cobs.si/api/comet_list.api?is-observed=true&cur-mag=8",
        "page": "https://cobs.si/",
        "licence": "CC BY-NC-SA 4.0",
        "rafraichir_s": 12 * 3600,
        "garder_s": 10 * 86400,
    },
    "orbites": {
        "nom": "Minor Planet Center",
        "url": "https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt",
        "page": "https://www.minorplanetcenter.net/",
        "licence": "Données publiques (UAI)",
        "rafraichir_s": 2 * 86400,
        "garder_s": 60 * 86400,  # une orbite de comète reste bonne des semaines
    },
}

MAGNITUDE_OEIL_NU = 6.0  # au-delà, invisible à l'œil nu même sous un ciel noir
KP_MAXI = 9.0


def dossier():
    defaut = Path(settings.BASE_DIR) / "donnees_skyfield" / "externes"
    return Path(getattr(settings, "DOSSIER_SOURCES_EXTERNES", defaut))


def _telecharger(url):
    """Contenu (texte) d'une adresse. Remplacé dans les tests (aucun accès réseau en test)."""
    requete = urllib.request.Request(url, headers={"User-Agent": "Index-Stellaire (projet etudiant)"})
    with urllib.request.urlopen(requete, timeout=DELAI_RESEAU_S) as reponse:
        return reponse.read().decode("utf-8", errors="replace")


def lire_source(cle, valider):
    """(texte, etat, age_s) : etat « ok » (frais), « cache » (copie locale, réseau absent) ou
    « indisponible » (texte None). `valider(texte)` lève ValueError si le contenu est invalide."""
    source = SOURCES[cle]
    fichier = dossier() / f"{cle}.txt"
    texte, age = None, None
    if fichier.is_file():
        age = time.time() - fichier.stat().st_mtime
        if age < source["garder_s"]:
            texte = fichier.read_text(encoding="utf-8")
    if texte is not None and age < source["rafraichir_s"]:
        return texte, "ok", age
    if not cache.get(f"source-echec:{cle}"):
        try:
            neuf = _telecharger(source["url"])
            valider(neuf)
        except (OSError, ValueError):
            cache.set(f"source-echec:{cle}", True, DELAI_APRES_ECHEC_S)
        else:
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(neuf, encoding="utf-8")
            return neuf, "ok", 0.0
    if texte is not None:
        return texte, "cache", age
    return None, "indisponible", None


# --- Aurores ----------------------------------------------------------------------------------

# Pôle géomagnétique Nord (modèle IGRF, 2025) : la latitude géomagnétique compte pour les aurores
POLE_GEOMAGNETIQUE = (80.8, -72.7)


def latitude_geomagnetique(lat, lon):
    p_lat, p_lon = map(math.radians, POLE_GEOMAGNETIQUE)
    la, lo = math.radians(lat), math.radians(lon)
    s = math.sin(la) * math.sin(p_lat) + math.cos(la) * math.cos(p_lat) * math.cos(lo - p_lon)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def kp_necessaire(lat, lon):
    """Kp à partir duquel une aurore peut se voir bas sur l'horizon (vers le pôle) : règle
    approximative de l'ovale auroral, 66° de latitude géomagnétique par temps calme, 2° plus
    au sud par point de Kp (Kp 9 : vers 48°). Indicatif : une aurore reste imprévisible."""
    return max(0.0, (66.0 - abs(latitude_geomagnetique(lat, lon))) / 2.0)


def lire_kp(texte):
    """[(instant UTC, kp, prevu)] depuis le JSON du NOAA. Accepte les deux formes connues :
    liste de listes avec une ligne d'en-tête, ou liste d'objets. ValueError si illisible."""
    donnees = json.loads(texte)
    if not isinstance(donnees, list) or not donnees:
        raise ValueError("prévision Kp vide")
    if isinstance(donnees[0], list):
        entete = [str(c).lower() for c in donnees[0]]
        lignes = [dict(zip(entete, l)) for l in donnees[1:]]
    else:
        lignes = donnees
    resultat = []
    for l in lignes:
        quand = datetime.fromisoformat(str(l["time_tag"]).replace("Z", "").replace(" ", "T")).replace(tzinfo=timezone.utc)
        kp = float(l["kp"])
        prevu = str(l.get("observed", "")).lower() in ("predicted", "estimated")
        resultat.append((quand, kp, prevu))
    if not resultat:
        raise ValueError("prévision Kp vide")
    return resultat


def aurores(lat, lon, alt, debut, fin):
    """Événements « aurore possible » : créneaux de 3 h prévus avec un Kp suffisant, de nuit."""
    texte, etat, age = lire_source("aurores", lire_kp)
    statut = _statut("aurores", etat, age)
    if texte is None:
        return [], statut
    seuil = kp_necessaire(lat, lon)
    lieu = wgs84.latlon(lat, lon, elevation_m=alt)
    terre_lieu = astro._ephemerides()["earth"] + lieu
    nord = lat >= 0
    evenements = []
    ts = astro._timescale()
    for quand, kp, _ in lire_kp(texte):
        milieu = ts.tt_jd(ts.from_datetime(quand).tt + 1.5 / 24)  # milieu du créneau de 3 h
        if kp < seuil or not debut.tt <= milieu.tt <= fin.tt:
            continue
        soleil = terre_lieu.at(milieu).observe(astro._ephemerides()["sun"]).apparent().altaz()[0].degrees
        if soleil > -12:
            continue  # il fait jour ou trop clair
        evenements.append({
            "type": "aurore",
            "titre": f"Aurore {'boréale' if nord else 'australe'} possible (Kp {kp:.0f} prévu)",
            "instant": milieu.utc_iso(),
            "kp": round(kp, 1),
            "kp_necessaire": round(seuil, 1),
            "important": True,
            "objet_id": None,
            "direction": {"azimut": 0.0 if nord else 180.0, "elevation": 15.0},  # bas vers le pôle
            "source": SOURCES["aurores"]["nom"],
        })
    # Un seul événement par nuit : le créneau au Kp le plus fort
    par_nuit = {}
    for e in evenements:
        nuit = (datetime.fromisoformat(e["instant"].replace("Z", "+00:00")).timestamp() - 12 * 3600) // 86400
        if nuit not in par_nuit or e["kp"] > par_nuit[nuit]["kp"]:
            par_nuit[nuit] = e
    return list(par_nuit.values()), statut


# --- Comètes ----------------------------------------------------------------------------------

def lire_cometes_cobs(texte):
    """[(nom court, nom complet, magnitude actuelle)] depuis la réponse JSON de COBS."""
    donnees = json.loads(texte)
    objets = donnees.get("objects") if isinstance(donnees, dict) else None
    if objets is None:
        raise ValueError("réponse COBS sans « objects »")
    resultat = []
    for o in objets:
        try:
            mag = float(o.get("current_mag"))
        except (TypeError, ValueError):
            continue
        nom = str(o.get("name") or "").strip()
        if nom:
            resultat.append((nom, str(o.get("fullname") or nom).strip(), mag))
    return resultat


def lire_orbites(texte):
    from skyfield.data import mpc
    df = mpc.load_comets_dataframe(io.BytesIO(texte.encode("utf-8")))
    if len(df) == 0:
        raise ValueError("fichier d'orbites vide")
    return df


def _ligne_orbite(df, nom):
    """La ligne d'orbite MPC d'une comète nommée par COBS (« C/2023 A3 », « 12P »)."""
    for i, designation in enumerate(df["designation"]):
        d = str(designation)
        if d.split(" (")[0] == nom or d.startswith(nom + "/"):
            return df.iloc[i]
    return None


def cometes(lat, lon, alt, debut, fin):
    """Comètes visibles à l'œil nu (magnitude ≤ 6) et observables de nuit dans la fenêtre :
    un événement par comète, au meilleur moment de la première nuit où elle monte à 10°."""
    from skyfield.data import mpc
    from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN

    texte, etat, age = lire_source("cometes", lire_cometes_cobs)
    statuts = [_statut("cometes", etat, age)]
    if texte is None:
        return [], statuts
    brillantes = [c for c in lire_cometes_cobs(texte) if c[2] <= MAGNITUDE_OEIL_NU]
    if not brillantes:
        return [], statuts
    texte_orbites, etat_o, age_o = lire_source("orbites", lire_orbites)
    statuts.append(_statut("orbites", etat_o, age_o))
    if texte_orbites is None:
        return [], statuts
    df = lire_orbites(texte_orbites)
    ts = astro._timescale()
    eph = astro._ephemerides()
    lieu = wgs84.latlon(lat, lon, elevation_m=alt)
    terre_lieu = eph["earth"] + lieu
    evenements = []
    for nom, nom_complet, mag in brillantes:
        ligne = _ligne_orbite(df, nom)
        if ligne is None:
            continue
        comete = eph["sun"] + mpc.comet_orbit(ligne, ts, GM_SUN)
        n = int((fin.tt - debut.tt) * 144) + 1  # pas de 10 min
        instants = ts.tt_jd(debut.tt + np.arange(n) / 144.0)
        hauteur, azimut, _ = terre_lieu.at(instants).observe(comete).apparent().altaz()
        soleil = terre_lieu.at(instants).observe(eph["sun"]).apparent().altaz()[0].degrees
        possible = (soleil < -12) & (hauteur.degrees >= 10)
        if not possible.any():
            continue
        premier = int(np.argmax(possible))
        nuit = slice(premier, min(n, premier + 144))  # la première nuit favorable
        k = premier + int(np.argmax(np.where(possible[nuit], hauteur.degrees[nuit], -999)))
        evenements.append({
            "type": "comete",
            "titre": f"Comète {nom_complet} (magnitude {mag:.1f})".replace(".", ","),
            "instant": instants[k].utc_iso(),
            "magnitude": round(mag, 1),
            "important": mag <= 4.5,
            "objet_id": None,
            "direction": {"azimut": round(float(azimut.degrees[k]), 1), "elevation": round(float(hauteur.degrees[k]), 1)},
            "source": "COBS (CC BY-NC-SA 4.0) · Minor Planet Center",
        })
    return evenements, statuts


# --- Ensemble ---------------------------------------------------------------------------------

def _statut(cle, etat, age):
    s = SOURCES[cle]
    return {
        "nom": s["nom"],
        "page": s["page"],
        "licence": s["licence"],
        "etat": etat,  # ok, cache, indisponible
        "age_h": None if age is None else round(age / 3600, 1),
    }


def evenements_externes(lat, lon, alt, debut, fin):
    """(événements, statuts des sources). Ne lève jamais : une source en panne est signalée."""
    tous, statuts = [], []
    for fonction in (aurores, cometes):
        try:
            evs, st = fonction(lat, lon, alt, debut, fin)
        except Exception:  # noqa: BLE001 — une source externe ne doit jamais casser la page
            import logging
            logging.getLogger(__name__).exception("Source externe en erreur (%s)", fonction.__name__)
            evs, st = [], []
        tous += evs
        statuts += st if isinstance(st, list) else [st]
    return tous, statuts

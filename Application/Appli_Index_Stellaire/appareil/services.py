"""Logique métier du pointage, indépendante de HTTP (testable seule)."""

import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction

from ciel import satellites
from ciel.astro import altaz, radec_depuis_altaz, trajectoire

from .models import Appareil, Commande


def lieu_observation(appareil=None, secours=None):
    """Où se trouve le bras : la position GPS qu'il a rapportée (Partie 6.2), sinon `secours`
    (la position partagée par un navigateur, Partie 6.4), sinon le lieu par défaut des réglages.
    Indispensable pour l'ISS : 10 km d'écart = 1,5° d'erreur."""
    if appareil is not None and appareil.latitude is not None and appareil.longitude is not None:
        return {
            "latitude": appareil.latitude,
            "longitude": appareil.longitude,
            "altitude_m": appareil.altitude_m if appareil.altitude_m is not None else 0,
        }
    if secours is not None:
        return secours
    return settings.LIEU_PAR_DEFAUT


def appareil_principal():
    """Le projet est mono-appareil : on prend le premier. None s'il n'y en a pas."""
    return Appareil.objects.order_by("id").first()


def commande_active(appareil):
    return appareil.commandes.filter(active=True).select_related("objet", "appareil").first()


@transaction.atomic
def definir_cible(appareil, objet):
    """Remplace la commande en cours par un pointage sur `objet`."""
    appareil.commandes.filter(active=True).update(active=False)
    return Commande.objects.create(appareil=appareil, objet=objet)


@transaction.atomic
def definir_point(appareil, ra, dec, nom=""):
    """Partie 8.4 (F18) : remplace la commande en cours par un point fixe du ciel (ra, dec en
    degrés, J2000). Il tourne avec le ciel ; sous l'horizon, le bras pointe à travers la Terre."""
    appareil.commandes.filter(active=True).update(active=False)
    return Commande.objects.create(appareil=appareil, ra=ra % 360, dec=dec, nom_cible=nom)


# Partie 8.5 (F22) : visite guidée
ETAPES_MAX = 20
DUREE_ETAPE_MAX_MIN = 240


@transaction.atomic
def definir_visite(appareil, etapes, debut):
    """Remplace la commande en cours par une visite guidée. etapes : [{objet (ObjetCeleste) ou
    ra/dec/nom, duree_s}], déjà vérifiées ; debut : datetime (avec fuseau)."""
    appareil.commandes.filter(active=True).update(active=False)
    programme = []
    for e in etapes:
        objet = e.get("objet")
        if objet is not None:
            programme.append({"objet_id": objet.id, "ra": None, "dec": None, "nom": objet.nom,
                              "identifiant": objet.identifiant_skyfield, "duree_s": e["duree_s"]})
        else:
            ra = e["ra"] % 360
            programme.append({"objet_id": None, "ra": ra, "dec": e["dec"], "nom": e.get("nom") or "Point du ciel",
                              "identifiant": f"radec:{ra},{e['dec']}", "duree_s": e["duree_s"]})
    premiere = etapes[0]
    return Commande.objects.create(
        appareil=appareil,
        objet=premiere.get("objet"),
        ra=None if premiere.get("objet") else premiere["ra"] % 360,
        dec=None if premiere.get("objet") else premiere["dec"],
        programme=programme,
        debut_programme=debut,
    )


def etape_resumee(commande, quand=None):
    """Champ « etape » de la synchronisation : {numero, total, fin} ou None hors visite."""
    e = commande.etape_a(quand)
    if e is None:
        return None
    return {"numero": e[0] + 1, "total": len(commande.programme),
            "fin": e[3].isoformat().replace("+00:00", "Z") if e[3] else None}


def programme_resume(commande, quand=None):
    """Champ « programme » de l'état (interface) : la visite étape par étape, ou None."""
    e = commande.etape_a(quand)
    if e is None:
        return None
    iso = lambda d: d.isoformat().replace("+00:00", "Z") if d else None  # noqa: E731
    return {
        "debut": iso(commande.debut_programme),
        "etape": e[0] + 1,  # numéro de l'étape en cours (ou à venir), à partir de 1
        "etapes": [
            {"nom": et["nom"], "objet_id": et["objet_id"],
             "coordonnees": None if et["objet_id"] is not None else {"ra": et["ra"], "dec": et["dec"]},
             "duree_min": round(et["duree_s"] / 60), "debut": iso(d), "fin": iso(f)}
            for _, et, d, f in commande.etapes_datees()
        ],
    }


def arreter(appareil):
    appareil.commandes.filter(active=True).update(active=False)


def cible_de(commande, instant=None, secours=None):
    """Où doit pointer le bras maintenant pour viser l'objet de la commande.

    L'élévation peut être négative : le bras est une structure ouverte, il sait
    pointer à travers la Terre (objets de l'autre côté du globe)."""
    lieu = lieu_observation(commande.appareil, secours)
    quand = instant.utc_datetime() if instant is not None else None
    elevation, azimut = altaz(
        commande.identifiant_a(quand),
        lieu["latitude"], lieu["longitude"], lieu["altitude_m"],
        instant,
    )
    return {"azimut": round(azimut, 3), "elevation": round(elevation, 3), "visible": elevation > 0}


# Partie 6.1 : trajectoire longue, pour que le bras suive sa cible même sans réseau
PAS_TRAJECTOIRE_S = 60  # une position par minute ; l'appareil interpole entre deux points
DUREE_TRAJECTOIRE_H = 48  # l'autonomie visée

# Partie 6.2 : un satellite va jusqu'à 1 °/s. Interpoler à 60 s donne jusqu'à 21° d'erreur,
# à 5 s 0,4°. On envoie donc un point toutes les 5 s, sur 6 h seulement (4 321 points) : le
# robot calcule lui-même la suite avec SGP4 à partir du TLE joint, et compare à ces points.
PAS_SATELLITE_S = 5
DUREE_SATELLITE_H = 6


def est_satellite(objet):
    return satellites.numero_de(objet.identifiant_skyfield) is not None


def trajectoire_de(commande, debut, heures=DUREE_TRAJECTOIRE_H, pas_s=PAS_TRAJECTOIRE_S):
    """Positions [azimut, élévation] (degrés, 2 décimales) du bras pour viser l'objet de la
    commande, une tous les `pas_s` secondes de `debut` à `debut + heures`, bornes comprises."""
    lieu = lieu_observation(commande.appareil)
    args = (lieu["latitude"], lieu["longitude"], lieu["altitude_m"], debut, heures, pas_s / 60)
    if not commande.programme:
        points = trajectoire(commande.identifiant_a(debut.utc_datetime()), *args)
        return [[round(p["azimut"], 2), round(p["elevation"], 2)] for p in points]
    # Visite guidée (8.5) : chaque point vise l'étape en cours à son instant. Le format ne change
    # pas : le robot suit les points sans savoir qu'il s'agit d'une visite.
    t0 = debut.utc_datetime()
    n = int(round(heures * 3600 / pas_s)) + 1
    choix = [commande.identifiant_a(t0 + timedelta(seconds=i * pas_s)) for i in range(n)]
    par_cible = {ident: trajectoire(ident, *args) for ident in set(choix)}
    return [[round(par_cible[c][i]["azimut"], 2), round(par_cible[c][i]["elevation"], 2)] for i, c in enumerate(choix)]


def trajectoire_pour_appareil(commande, debut, heures=DUREE_TRAJECTOIRE_H):
    """Tout ce que l'appareil télécharge pour suivre seul : {pas_s, points, tle, lieu}.
    Satellite : pas de 5 s, 6 h au plus, et son TLE ; autre astre : pas de 60 s, tle None.
    Lève ValueError (dont satellites.TleIndisponible) si le calcul est impossible."""
    lieu = lieu_observation(commande.appareil)
    tle = None
    pas_s = PAS_TRAJECTOIRE_S
    if satellites.numero_de(commande.identifiant) is not None:
        d = satellites.tle(satellites.numero_de(commande.identifiant))
        tle = {k: d[k] for k in ("nom", "ligne1", "ligne2", "epoque")}
        pas_s = PAS_SATELLITE_S
        heures = min(heures, DUREE_SATELLITE_H)
    return {
        "pas_s": pas_s,
        "points": trajectoire_de(commande, debut, heures, pas_s),
        "tle": tle,
        "lieu": {k: lieu[k] for k in ("latitude", "longitude", "altitude_m")},
    }


def position_ciel_du_bras(appareil, secours=None):
    """Où pointe le bras, en coordonnées du ciel (ra, dec) : de quoi le dessiner sur la carte.
    None tant que l'appareil n'a jamais rapporté sa position."""
    if appareil.azimut is None or appareil.elevation is None:
        return None
    lieu = lieu_observation(appareil, secours)
    ra, dec = radec_depuis_altaz(
        appareil.azimut, appareil.elevation, lieu["latitude"], lieu["longitude"], lieu["altitude_m"]
    )
    return {"ra": round(ra, 3), "dec": round(dec, 3)}


def ecart_angulaire(a, b):
    """Angle (degrés) entre deux directions (azimut, élévation), par la trigonométrie sphérique."""
    az1, el1, az2, el2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    c = math.sin(el1) * math.sin(el2) + math.cos(el1) * math.cos(el2) * math.cos(az1 - az2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))

"""Partie 14 : jamais de pointage vers le Soleil ni trop près de lui.

Le bras porte (ou portera) une caméra et un laser : viser le Soleil abîme le capteur, et quelqu'un
pourrait regarder dans l'axe. Le serveur refuse donc toute commande dont la cible passe à moins de
ANGLE_MINI_SOLEIL degrés du Soleil pendant le temps où le bras la suivra (48 h pour un astre ou
un point du ciel, 6 h pour un satellite, la durée de chaque étape pour une visite).
On ne compte que les moments où le Soleil est levé ou presque (hauteur > -ANGLE_MINI_SOLEIL) :
le reste du temps, viser « vers le Soleil » revient à viser le sol, sans danger. Sans cela,
la Lune autour de la nouvelle Lune ou l'ISS seraient refusées sans raison.

L'équipe robot doit AUSSI faire ce contrôle dans le firmware (le STM32 calcule l'ISS lui-même) :
le serveur n'est qu'une première barrière.
"""

from datetime import timedelta

import numpy as np

from ciel import astro, satellites

ANGLE_MINI_SOLEIL = 10.0  # degrés
PAS_ASTRE_S = 1800  # un astre ou un point fixe s'approche du Soleil de moins d'1° par heure (Lune : 0,5°)
PAS_SATELLITE_S = 10  # l'ISS traverse le ciel en quelques minutes


class TropPresDuSoleil(ValueError):
    def __init__(self, nom, separation):
        self.nom = nom
        self.separation = separation
        super().__init__(
            f"{nom} : pointage refusé, trop près du Soleil ({separation:.1f}° ; il faut au moins "
            f"{ANGLE_MINI_SOLEIL:.0f}°). Ne jamais diriger le bras, une caméra ou un laser vers le Soleil."
        )


def separation_mini(identifiant, lieu, debut, duree_s):
    """Plus petit écart (degrés) entre la cible et le Soleil, vus du lieu, de `debut` (datetime avec
    fuseau) à `debut + duree_s`, aux instants où le Soleil est levé ou presque (180 s'il n'y en a pas)."""
    pas = PAS_SATELLITE_S if satellites.numero_de(identifiant) is not None else PAS_ASTRE_S
    n = int(duree_s // pas) + 2  # bornes comprises
    t0 = astro.instant_depuis(debut)
    t = astro._timescale().tt_jd(t0.tt + np.minimum(np.arange(n) * pas, duree_s) / 86400.0)
    args = (lieu["latitude"], lieu["longitude"], lieu["altitude_m"], t)
    cible = astro._vu_du_lieu(identifiant, *args, apparente=False)
    soleil = astro._vu_du_lieu("sun", *args, apparente=False)
    hauteur_soleil = astro._vu_du_lieu("sun", *args).altaz()[0].degrees
    jour = hauteur_soleil > -ANGLE_MINI_SOLEIL
    if identifiant == "sun":
        return 0.0 if np.any(jour) else 180.0  # le Soleil lui-même : refusé dès qu'il peut être visible
    if not np.any(jour):
        return 180.0
    return float(np.min(np.where(jour, cible.separation_from(soleil).degrees, 180.0)))


def verifier(identifiant, nom, lieu, debut, duree_s):
    """Lève TropPresDuSoleil si la cible passe trop près du Soleil."""
    separation = separation_mini(identifiant, lieu, debut, duree_s)
    if separation < ANGLE_MINI_SOLEIL:
        raise TropPresDuSoleil(nom, separation)


def verifier_visite(etapes, lieu, debut):
    """etapes : [{"identifiant", "nom", "duree_s"}] dans l'ordre ; chaque étape sur sa fenêtre.
    La dernière étape reste visée après la fin de la visite : on la vérifie sur 48 h."""
    instant = debut
    for i, e in enumerate(etapes):
        duree = e["duree_s"] if i < len(etapes) - 1 else max(e["duree_s"], 48 * 3600)
        verifier(e["identifiant"], e["nom"], lieu, instant, duree)
        instant += timedelta(seconds=e["duree_s"])

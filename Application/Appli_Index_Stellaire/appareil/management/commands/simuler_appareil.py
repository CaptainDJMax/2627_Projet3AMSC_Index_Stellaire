"""Simule le bras : mêmes échanges HTTP que le futur firmware de l'ESP32.

    python manage.py simuler_appareil

Le simulateur ne touche pas à la base de données du serveur pour pointer : il
parle à l'API comme le ferait le vrai appareil. Ainsi, quand le matériel existera,
seul l'émetteur changera, pas le protocole.

Partie 6.1 : autonomie. À chaque nouvelle commande (son id change), l'appareil
télécharge la trajectoire longue (GET /api/appareil/trajectoire/, 48 h, une position
par minute) et suit la cible en interpolant entre deux points. Si le serveur ne
répond plus, il continue à suivre seul jusqu'à la fin de la trajectoire.
C'est ce comportement que le firmware devra reproduire.

Partie 6.2 : pour un satellite (ISS), la trajectoire contient aussi son TLE. Le simulateur
calcule alors la position lui-même avec SGP4 (`position_sgp4` ci-dessous : c'est le calcul
que le STM32 devra faire, étape par étape) et la compare aux points du serveur.
Il retélécharge la trajectoire quand il en reste moins d'une heure (TLE rafraîchi au passage).
"""

import json
import math
import time
import urllib.error
import urllib.request
from datetime import datetime

from django.core.management.base import BaseCommand
from sgp4.api import Satrec, jday

from appareil.models import Appareil

ERREURS_RESEAU = (urllib.error.URLError, TimeoutError, ConnectionError, ValueError)
MARGE_RETELECHARGEMENT_S = 3600  # en ligne, on redemande la trajectoire quand il en reste moins d'1 h
AUTONOMIE_SGP4_S = 48 * 3600  # avec un TLE, suivi seul jusqu'à 48 h après le téléchargement


def ecart_azimut(depuis, vers):
    """Plus court chemin signé (-180..180] : la bague collectrice permet de tourner sans fin."""
    return (vers - depuis + 540) % 360 - 180


def position_sur_trajectoire(traj, t):
    """Position {azimut, elevation} à l'instant t (secondes depuis 1970), interpolée entre les deux
    points qui l'encadrent ; None avant le début ou après la fin. traj = {debut, pas_s, points}.
    L'azimut passe par le plus court chemin (350° -> 10° passe par le nord)."""
    x = (t - traj["debut"]) / traj["pas_s"]
    i = math.floor(x)
    points = traj["points"]
    if i < 0 or i >= len(points) - 1:
        if i == len(points) - 1 and x == i:
            az, el = points[i]
            return {"azimut": az % 360, "elevation": el}
        return None
    f = x - i
    (az1, el1), (az2, el2) = points[i], points[i + 1]
    return {"azimut": (az1 + ecart_azimut(az1, az2) * f) % 360, "elevation": el1 + (el2 - el1) * f}


# --- Partie 6.2 : le calcul SGP4 que le firmware du STM32 devra reproduire -----------------------
# Étapes : TLE -> SGP4 (position dans le repère TEME, en km) -> rotation de la Terre (temps
# sidéral) -> repère terrestre -> écart avec la position du robot (WGS84) -> est/nord/haut
# -> azimut et élévation. Tout en double précision (le STM32H723 a une FPU double précision).
# En C : bibliothèque SGP4 de référence de David Vallado (sgp4.cpp, la même que ce module Python).

WGS84_A_KM = 6378.137
WGS84_F = 1 / 298.257223563


def temps_sideral_greenwich(jd_ut1):
    """GMST en radians (formule IAU 1982, celle de Vallado, `gstime`)."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    secondes = (-6.2e-6 * t ** 3 + 0.093104 * t ** 2
                + (876600.0 * 3600 + 8640184.812866) * t + 67310.54841)
    return math.radians(secondes / 240.0) % (2 * math.pi)  # 240 s de temps = 1°


def lieu_terrestre_km(latitude, longitude, altitude_m):
    """Position du robot dans le repère terrestre (x, y, z) en km, ellipsoïde WGS84."""
    phi, lam = math.radians(latitude), math.radians(longitude)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A_KM / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    h = altitude_m / 1000.0
    return ((n + h) * math.cos(phi) * math.cos(lam),
            (n + h) * math.cos(phi) * math.sin(lam),
            (n * (1 - e2) + h) * math.sin(phi))


def position_sgp4(tle, lieu, t):
    """{azimut, elevation} du satellite vu du lieu {latitude, longitude, altitude_m}, à l'instant t
    (secondes depuis 1970, UTC). None si SGP4 échoue (TLE invalide ou trop ancien)."""
    sat = Satrec.twoline2rv(tle["ligne1"], tle["ligne2"])
    jd, fr = jday(1970, 1, 1, 0, 0, 0)
    fr += t / 86400.0
    erreur, (x, y, z), _ = sat.sgp4(jd, fr)
    if erreur:
        return None
    # TEME -> repère terrestre : rotation de -GMST autour de l'axe des pôles
    g = temps_sideral_greenwich(jd + fr)
    xt, yt = math.cos(g) * x + math.sin(g) * y, -math.sin(g) * x + math.cos(g) * y
    ox, oy, oz = lieu_terrestre_km(lieu["latitude"], lieu["longitude"], lieu["altitude_m"])
    dx, dy, dz = xt - ox, yt - oy, z - oz
    # Repère local est / nord / haut
    phi, lam = math.radians(lieu["latitude"]), math.radians(lieu["longitude"])
    est = -math.sin(lam) * dx + math.cos(lam) * dy
    nord = (-math.sin(phi) * math.cos(lam) * dx - math.sin(phi) * math.sin(lam) * dy
            + math.cos(phi) * dz)
    haut = (math.cos(phi) * math.cos(lam) * dx + math.cos(phi) * math.sin(lam) * dy
            + math.sin(phi) * dz)
    return {"azimut": math.degrees(math.atan2(est, nord)) % 360,
            "elevation": math.degrees(math.atan2(haut, math.hypot(est, nord)))}


def ecart_controle(traj):
    """Plus grand écart (degrés) entre le calcul SGP4 local et les points du serveur :
    le test que le firmware fera pour vérifier son SGP4 (attendu : moins de 0,4°)."""
    pire = 0.0
    for i in range(0, len(traj["points"]), 12):  # un point par minute suffit
        az, el = traj["points"][i]
        p = position_sgp4(traj["tle"], traj["lieu"], traj["debut"] + i * traj["pas_s"])
        if p is None:
            return None
        a1, e1, a2, e2 = map(math.radians, (az, el, p["azimut"], p["elevation"]))
        c = math.sin(e1) * math.sin(e2) + math.cos(e1) * math.cos(e2) * math.cos(a1 - a2)
        pire = max(pire, math.degrees(math.acos(max(-1.0, min(1.0, c)))))
    return pire


def consigne_de(traj, t, avec_sgp4=True):
    """Où viser à l'instant t : SGP4 si la trajectoire a un TLE, sinon interpolation des points."""
    if avec_sgp4 and traj.get("tle"):
        if not traj["debut"] <= t <= traj["debut"] + AUTONOMIE_SGP4_S:
            return None
        p = position_sgp4(traj["tle"], traj["lieu"], t)
        if p is not None:
            return p
    return position_sur_trajectoire(traj, t)


def a_retelecharger(traj, t):
    """En ligne : redemander la trajectoire quand il en reste moins de MARGE_RETELECHARGEMENT_S."""
    fin = traj["debut"] + (len(traj["points"]) - 1) * traj["pas_s"]
    return fin - t < MARGE_RETELECHARGEMENT_S


def instant_unix(texte_iso):
    return datetime.fromisoformat(texte_iso.replace("Z", "+00:00")).timestamp()


class Command(BaseCommand):
    help = "Simule l'appareil : envoie son état au serveur et suit la consigne reçue, même hors ligne."

    def add_arguments(self, parser):
        parser.add_argument("--url", default="http://127.0.0.1:8000", help="adresse du serveur")
        parser.add_argument("--jeton", help="jeton de l'appareil (par défaut : celui du premier appareil en base)")
        parser.add_argument("--vitesse", type=float, default=20.0, help="vitesse maxi des axes, en °/s")
        parser.add_argument("--intervalle", type=float, default=1.0, help="secondes entre deux synchronisations")
        parser.add_argument("--sans-trajectoire", action="store_true",
                            help="ancien comportement : suivre seulement la cible reçue à chaque synchronisation")
        parser.add_argument("--sans-sgp4", action="store_true",
                            help="satellites : interpoler les points au lieu de calculer avec SGP4")
        parser.add_argument("--lieu", nargs=3, type=float, metavar=("LAT", "LON", "ALT_M"),
                            help="position GPS simulée, envoyée au serveur (ex. 45.76 4.84 170)")

    def handle(self, *args, **options):
        jeton = options["jeton"]
        if not jeton:
            appareil = Appareil.objects.order_by("id").first() or Appareil.objects.create()
            jeton = appareil.jeton
            self.stdout.write(f"Appareil « {appareil.nom} » (jeton lu en base).")

        base = options["url"].rstrip("/")
        vitesse = options["vitesse"]
        intervalle = options["intervalle"]
        avec_trajectoire = not options["sans_trajectoire"]
        avec_sgp4 = not options["sans_sgp4"]
        gps = options["lieu"]

        # État physique simulé : le bras démarre vers le nord, à l'horizontale
        azimut, elevation, batterie = 0.0, 0.0, 100.0
        cible = None  # dernière cible reçue du serveur
        commande_id = None
        nom_objet = None
        traj = None  # trajectoire longue de la commande en cours
        en_ligne = True
        mode = "repos"
        prochaine_sync = 0.0
        dernier = time.monotonic()

        self.stdout.write(f"Simulation vers {base} — vitesse maxi {vitesse}°/s. Ctrl+C pour arrêter.")
        try:
            while True:
                maintenant = time.monotonic()
                dt = maintenant - dernier
                dernier = maintenant

                # --- Consigne : la trajectoire si on l'a, sinon la dernière cible reçue -----
                consigne = consigne_de(traj, time.time(), avec_sgp4) if traj else None
                if consigne is None and en_ligne:
                    consigne = cible
                if consigne is None and traj and not en_ligne:
                    traj = None  # trajectoire terminée et serveur muet : on s'arrête

                # --- Physique : les deux axes rejoignent la consigne à vitesse limitée ------
                if consigne is not None:
                    pas = vitesse * dt
                    d_az = ecart_azimut(azimut, consigne["azimut"])
                    d_el = consigne["elevation"] - elevation
                    azimut = (azimut + max(-pas, min(pas, d_az))) % 360
                    elevation = max(-90.0, min(90.0, elevation + max(-pas, min(pas, d_el))))
                    arrive = abs(d_az) < 0.05 and abs(d_el) < 0.05
                    mode = "suivi" if arrive else "deplacement"
                else:
                    mode = "repos"
                batterie = max(0.0, batterie - 0.01 * dt)

                # --- Réseau : une synchronisation par intervalle ---------------------------
                if maintenant >= prochaine_sync:
                    prochaine_sync = maintenant + intervalle
                    corps = {
                        "azimut": round(azimut, 3), "elevation": round(elevation, 3),
                        "batterie": round(batterie), "mode": mode,
                    }
                    if gps:
                        corps.update(latitude=gps[0], longitude=gps[1], altitude_m=gps[2])
                    try:
                        reponse = self.requete("POST", base + "/api/appareil/sync/", jeton, corps)
                    except ERREURS_RESEAU as erreur:
                        en_ligne = False
                        etat = ("aucune trajectoire en mémoire" if not traj else
                                "suivi autonome (calcul SGP4)" if traj.get("tle") and avec_sgp4 else
                                "suivi autonome sur la trajectoire")
                        self.stdout.write(self.style.WARNING(
                            f"[hors ligne ] az={azimut:6.1f}° el={elevation:6.1f}° — serveur injoignable "
                            f"({type(erreur).__name__}), {etat}"
                        ))
                    else:
                        en_ligne = True
                        commande = reponse.get("commande")
                        intervalle = reponse.get("intervalle_ms", intervalle * 1000) / 1000
                        if commande is None:
                            cible, commande_id, traj, nom_objet = None, None, None, None
                        else:
                            cible = commande["cible"]
                            nom_objet = commande["objet"]["nom"]
                            nouvelle = commande["id"] != commande_id
                            if avec_trajectoire and (nouvelle or (traj and a_retelecharger(traj, time.time()))):
                                commande_id = commande["id"]
                                traj = self.telecharger_trajectoire(base, commande, jeton, avec_sgp4)
                        visee = f"→ {nom_objet}" if nom_objet else "(aucune consigne)"
                        if consigne:
                            visee += f" az={consigne['azimut']:.1f}° el={consigne['elevation']:.1f}°"
                        if traj:
                            visee += " [SGP4]" if traj.get("tle") and avec_sgp4 else " [trajectoire]"
                        self.stdout.write(f"[{mode:11}] az={azimut:6.1f}° el={elevation:6.1f}° bat={batterie:.0f}% {visee}")

                time.sleep(0.05)
        except KeyboardInterrupt:
            self.stdout.write("\nSimulation arrêtée.")

    def telecharger_trajectoire(self, base, commande, jeton, avec_sgp4=True):
        chemin = commande.get("trajectoire")
        if not chemin:
            return None
        try:
            d = self.requete("GET", base + chemin, jeton)
        except ERREURS_RESEAU as erreur:
            self.stdout.write(self.style.WARNING(f"Trajectoire indisponible ({erreur}) : suivi seconde par seconde."))
            return None
        if d.get("type") != "positions" or not d.get("points"):
            return None
        traj = {"debut": instant_unix(d["debut"]), "pas_s": d["pas_s"], "points": d["points"],
                "tle": d.get("tle"), "lieu": d.get("lieu")}
        heures = (len(d["points"]) - 1) * d["pas_s"] / 3600
        nom = commande["objet"]["nom"]
        if traj["tle"] and avec_sgp4:
            ecart = ecart_controle(traj)
            if ecart is None or ecart > 0.4:
                self.stdout.write(self.style.ERROR(
                    f"SGP4 en désaccord avec le serveur pour {nom} (écart {ecart}) : on suit les points."))
                traj["tle"] = None
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"TLE reçu pour {nom} (époque {traj['tle']['epoque']}) : calcul SGP4 sur l'appareil, "
                    f"écart avec le serveur {ecart:.3f}°."))
                return traj
        self.stdout.write(self.style.SUCCESS(
            f"Trajectoire reçue pour {nom} : {len(d['points'])} positions toutes les {d['pas_s']} s, "
            f"{heures:.0f} h d'autonomie."
        ))
        return traj

    @staticmethod
    def requete(methode, url, jeton, corps=None):
        requete = urllib.request.Request(
            url,
            data=json.dumps(corps).encode() if corps is not None else None,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {jeton}"},
            method=methode,
        )
        with urllib.request.urlopen(requete, timeout=5) as reponse:
            return json.load(reponse)

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
"""

import json
import math
import time
import urllib.error
import urllib.request
from datetime import datetime

from django.core.management.base import BaseCommand

from appareil.models import Appareil

ERREURS_RESEAU = (urllib.error.URLError, TimeoutError, ConnectionError, ValueError)


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
                consigne = position_sur_trajectoire(traj, time.time()) if traj else None
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
                    try:
                        reponse = self.requete("POST", base + "/api/appareil/sync/", jeton, corps)
                    except ERREURS_RESEAU as erreur:
                        en_ligne = False
                        etat = "suivi autonome sur la trajectoire" if traj else "aucune trajectoire en mémoire"
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
                            if commande["id"] != commande_id:  # nouvelle commande : nouvelle trajectoire
                                commande_id = commande["id"]
                                traj = self.telecharger_trajectoire(base, commande, jeton) if avec_trajectoire else None
                        visee = f"→ {nom_objet}" if nom_objet else "(aucune consigne)"
                        if consigne:
                            visee += f" az={consigne['azimut']:.1f}° el={consigne['elevation']:.1f}°"
                        if traj:
                            visee += " [trajectoire]"
                        self.stdout.write(f"[{mode:11}] az={azimut:6.1f}° el={elevation:6.1f}° bat={batterie:.0f}% {visee}")

                time.sleep(0.05)
        except KeyboardInterrupt:
            self.stdout.write("\nSimulation arrêtée.")

    def telecharger_trajectoire(self, base, commande, jeton):
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
        heures = (len(d["points"]) - 1) * d["pas_s"] / 3600
        self.stdout.write(self.style.SUCCESS(
            f"Trajectoire reçue pour {commande['objet']['nom']} : {len(d['points'])} positions, {heures:.0f} h d'autonomie."
        ))
        return {"debut": instant_unix(d["debut"]), "pas_s": d["pas_s"], "points": d["points"]}

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

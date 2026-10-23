"""Simule le bras : mêmes échanges HTTP que le futur firmware de l'ESP32.

    python manage.py simuler_appareil

Le simulateur ne touche pas à la base de données du serveur pour pointer : il
parle à l'API (POST /api/appareil/sync/) comme le ferait le vrai appareil. Ainsi,
quand le matériel existera, seul l'émetteur changera, pas le protocole.
"""

import json
import time
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand

from appareil.models import Appareil


def ecart_azimut(depuis, vers):
    """Plus court chemin signé (-180..180] : la bague collectrice permet de tourner sans fin."""
    return (vers - depuis + 540) % 360 - 180


class Command(BaseCommand):
    help = "Simule l'appareil : envoie son état au serveur et suit la consigne reçue."

    def add_arguments(self, parser):
        parser.add_argument("--url", default="http://127.0.0.1:8000", help="adresse du serveur")
        parser.add_argument("--jeton", help="jeton de l'appareil (par défaut : celui du premier appareil en base)")
        parser.add_argument("--vitesse", type=float, default=20.0, help="vitesse maxi des axes, en °/s")
        parser.add_argument("--intervalle", type=float, default=1.0, help="secondes entre deux synchronisations")

    def handle(self, *args, **options):
        jeton = options["jeton"]
        if not jeton:
            appareil = Appareil.objects.order_by("id").first() or Appareil.objects.create()
            jeton = appareil.jeton
            self.stdout.write(f"Appareil « {appareil.nom} » (jeton lu en base).")

        url = options["url"].rstrip("/") + "/api/appareil/sync/"
        vitesse = options["vitesse"]
        intervalle = options["intervalle"]

        # État physique simulé : le bras démarre vers le nord, à l'horizontale
        azimut, elevation, batterie = 0.0, 0.0, 100.0
        cible = None
        mode = "repos"
        prochaine_sync = 0.0
        dernier = time.monotonic()

        self.stdout.write(f"Simulation vers {url} — vitesse maxi {vitesse}°/s. Ctrl+C pour arrêter.")
        try:
            while True:
                maintenant = time.monotonic()
                dt = maintenant - dernier
                dernier = maintenant

                # --- Physique : les deux axes rejoignent la cible à vitesse limitée ----
                if cible is not None:
                    pas = vitesse * dt
                    d_az = ecart_azimut(azimut, cible["azimut"])
                    d_el = cible["elevation"] - elevation
                    azimut = (azimut + max(-pas, min(pas, d_az))) % 360
                    elevation = max(-90.0, min(90.0, elevation + max(-pas, min(pas, d_el))))
                    arrive = abs(d_az) < 0.05 and abs(d_el) < 0.05
                    mode = "suivi" if arrive else "deplacement"
                else:
                    mode = "repos"
                batterie = max(0.0, batterie - 0.01 * dt)

                # --- Réseau : une synchronisation par intervalle -----------------------
                if maintenant >= prochaine_sync:
                    prochaine_sync = maintenant + intervalle
                    corps = {
                        "azimut": round(azimut, 3), "elevation": round(elevation, 3),
                        "batterie": round(batterie), "mode": mode,
                    }
                    try:
                        reponse = self.synchroniser(url, jeton, corps)
                    except (urllib.error.URLError, TimeoutError, ValueError) as erreur:
                        self.stdout.write(self.style.WARNING(f"Serveur injoignable ({erreur}), on réessaie…"))
                    else:
                        commande = reponse.get("commande")
                        cible = commande["cible"] if commande else None
                        intervalle = reponse.get("intervalle_ms", intervalle * 1000) / 1000
                        visee = (
                            f"→ {commande['objet']['nom']} az={cible['azimut']:.1f}° el={cible['elevation']:.1f}°"
                            if commande else "(aucune consigne)"
                        )
                        self.stdout.write(f"[{mode:11}] az={azimut:6.1f}° el={elevation:6.1f}° bat={batterie:.0f}% {visee}")

                time.sleep(0.05)
        except KeyboardInterrupt:
            self.stdout.write("\nSimulation arrêtée.")

    @staticmethod
    def synchroniser(url, jeton, corps):
        requete = urllib.request.Request(
            url,
            data=json.dumps(corps).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {jeton}"},
            method="POST",
        )
        with urllib.request.urlopen(requete, timeout=5) as reponse:
            return json.load(reponse)

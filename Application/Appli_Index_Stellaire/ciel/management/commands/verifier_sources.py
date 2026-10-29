"""Partie 8.3 : vérifie les sources externes en temps réel (à lancer chez toi, avec internet).

    python manage.py verifier_sources

Télécharge chaque source (NOAA SWPC, COBS, Minor Planet Center), vérifie qu'on sait la lire et
affiche ce qu'on en tire. Si une source a changé de format, c'est ici qu'on le voit.
"""

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand

from ciel import astro, sources_externes as se


class Command(BaseCommand):
    help = "Télécharge et vérifie les sources externes d'événements (aurores, comètes)."

    def handle(self, *args, **options):
        cache.delete_many([f"source-echec:{c}" for c in se.SOURCES])
        lecteurs = {"aurores": se.lire_kp, "cometes": se.lire_cometes_cobs, "orbites": se.lire_orbites}
        tout_va_bien = True
        for cle, source in se.SOURCES.items():
            self.stdout.write(f"\n{source['nom']} ({source['url']})")
            texte = None
            try:
                texte = se._telecharger(source["url"])
                contenu = lecteurs[cle](texte)
            except Exception as erreur:  # noqa: BLE001 — on veut voir toute erreur
                tout_va_bien = False
                self.stdout.write(self.style.ERROR(f"  échec : {type(erreur).__name__} : {erreur}"))
                if texte:
                    self.stdout.write(f"  début de la réponse : {texte[:300]!r}")
                continue
            fichier = se.dossier() / f"{cle}.txt"
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(texte, encoding="utf-8")
            if cle == "aurores":
                prevus = [k for k in contenu if k[2]]
                maxi = max((k[1] for k in prevus), default=None)
                self.stdout.write(self.style.SUCCESS(f"  OK : {len(contenu)} créneaux de 3 h, {len(prevus)} prévus, Kp maxi prévu {maxi}"))
            elif cle == "cometes":
                brillantes = sorted([c for c in contenu if c[2] <= 10], key=lambda c: c[2])[:8]
                self.stdout.write(self.style.SUCCESS(f"  OK : {len(contenu)} comètes avec un éclat mesuré"))
                for nom, complet, mag in brillantes:
                    self.stdout.write(f"    {complet} : magnitude {mag}")
            else:
                self.stdout.write(self.style.SUCCESS(f"  OK : {len(contenu)} orbites de comètes"))

        lieu = settings.LIEU_PAR_DEFAUT
        debut = astro.maintenant()
        fin = debut.ts.tt_jd(debut.tt + 30)
        evs, statuts = se.evenements_externes(lieu["latitude"], lieu["longitude"], lieu["altitude_m"], debut, fin)
        self.stdout.write(f"\nKp nécessaire pour une aurore ici : {se.kp_necessaire(lieu['latitude'], lieu['longitude']):.1f}")
        self.stdout.write(f"Événements externes pour les 30 prochains jours : {len(evs)}")
        for e in evs:
            self.stdout.write(f"  {e['instant']} {e['titre']}")
        if tout_va_bien:
            self.stdout.write(self.style.SUCCESS("\nToutes les sources répondent et sont lisibles."))
        else:
            self.stdout.write(self.style.WARNING("\nUne source au moins pose problème : envoie cette sortie à Claude."))

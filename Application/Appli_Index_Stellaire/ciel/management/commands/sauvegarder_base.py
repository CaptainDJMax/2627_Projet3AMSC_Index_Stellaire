"""Partie 14 : sauvegarde de la base (journal d'observation, commandes, réglages de l'appareil).

    python manage.py sauvegarder_base            # garde les 10 dernières sauvegardes
    python manage.py sauvegarder_base --garder 30

La base n'est pas dans Git (le journal est personnel) : c'est la seule copie. Les sauvegardes vont
dans sauvegardes/ (ignoré par Git) ; copie-les de temps en temps ailleurs (clé USB, cloud).
La copie passe par SQLite lui-même : elle est cohérente même si le serveur tourne.
Pour restaurer : arrêter le serveur, remplacer db.sqlite3 par une sauvegarde (renommée).
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PREFIXE = "db-"


class Command(BaseCommand):
    help = "Copie db.sqlite3 dans sauvegardes/ (avec la date) et efface les plus anciennes."

    def add_arguments(self, parser):
        parser.add_argument("--garder", type=int, default=10, help="nombre de sauvegardes à garder (1 à 1000)")
        parser.add_argument("--dossier", default=None)

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError("Cette commande ne sait sauvegarder qu'une base SQLite.")
        garder = options["garder"]
        if not 1 <= garder <= 1000:
            raise CommandError("--garder doit être entre 1 et 1000")
        dossier = Path(options["dossier"] or settings.DOSSIER_SAUVEGARDES)
        dossier.mkdir(parents=True, exist_ok=True)
        cible = dossier / f"{PREFIXE}{datetime.now():%Y-%m-%d_%H-%M-%S}.sqlite3"
        connection.ensure_connection()
        destination = sqlite3.connect(cible)
        try:
            connection.connection.backup(destination)
        finally:
            destination.close()
        self.stdout.write(self.style.SUCCESS(f"Sauvegarde : {cible} ({cible.stat().st_size // 1024} Ko)"))
        anciennes = sorted(dossier.glob(f"{PREFIXE}*.sqlite3"))[:-garder]
        for f in anciennes:
            f.unlink()
        if anciennes:
            self.stdout.write(f"{len(anciennes)} ancienne(s) sauvegarde(s) effacée(s).")

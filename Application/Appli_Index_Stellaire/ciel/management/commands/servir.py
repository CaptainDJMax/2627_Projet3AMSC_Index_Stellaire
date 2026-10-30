"""Partie 14 : lancer le serveur « pour de vrai » (à la place de runserver).

    python manage.py servir                 # port 8000, joignable depuis le Wi-Fi de la maison
    python manage.py servir --port 8080

Waitress : serveur de production écrit en Python, qui marche pareil sous Windows et sous Linux
(Raspberry Pi). Avant de démarrer, les fichiers statiques sont rassemblés (collectstatic).
À utiliser avec {"production": true} dans config_locale.json. Toujours en HTTP pour l'instant :
Wi-Fi de la maison seulement (HTTPS en Partie 14.2).
"""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from index_stellaire.config_locale import ip_locale


class Command(BaseCommand):
    help = "Lance le serveur de production (Waitress) après collectstatic."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument("--hote", default="0.0.0.0", help="0.0.0.0 = joignable depuis le réseau local")
        parser.add_argument("--fils", type=int, default=8, help="requêtes traitées en même temps")

    def handle(self, *args, **options):
        try:
            from waitress import serve
        except ImportError:
            raise CommandError("Waitress manque : pip install -r requirements.txt")
        if not settings.PRODUCTION:
            self.stdout.write(self.style.WARNING(
                "Attention : mode développement (DEBUG activé). Pour la production, crée config_locale.json "
                'avec {"production": true} (voir config_locale.exemple.json).'
            ))
        else:
            self.stdout.write("Rassemblement des fichiers statiques...")
            call_command("collectstatic", interactive=False, verbosity=0)
        if not settings.CODE_PILOTAGE:
            self.stdout.write(self.style.WARNING("Aucun code de pilotage : le bras ne pourra pas être commandé."))

        from index_stellaire.wsgi import application

        port = options["port"]
        self.stdout.write(self.style.SUCCESS(f"Index Stellaire sur http://localhost:{port}/"))
        ip = ip_locale()
        if ip and options["hote"] == "0.0.0.0":
            self.stdout.write(f"Depuis le téléphone (même Wi-Fi) : http://{ip}:{port}/")
        self.stdout.write("Arrêt : Ctrl+C")
        serve(application, host=options["hote"], port=port, threads=options["fils"], ident="Index-Stellaire")

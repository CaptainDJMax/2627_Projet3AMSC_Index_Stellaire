"""Catalogue automatique : étoiles jusqu'à la magnitude 4,5, objets de Messier, Uranus et Neptune.

    python manage.py mettre_a_jour_catalogue              # internet : résumés Wikipédia et images (quelques minutes)
    python manage.py mettre_a_jour_catalogue --hors-ligne # seulement la base livrée avec l'appli (immédiat)
    python manage.py mettre_a_jour_catalogue --limite 20  # essai rapide sur 20 astres
    python manage.py mettre_a_jour_catalogue --refaire    # redemande tout, même ce qui a moins de 30 jours

`python manage.py servir` la lance tout seul, en arrière-plan, quand la dernière date de plus de 30 jours.
Les fiches écrites à la main (contenu/) ont toujours la priorité. Voir ciel/catalogue.py.
"""

from django.core.management.base import BaseCommand

from ciel import catalogue


class Command(BaseCommand):
    help = "Importe le catalogue automatique et, avec internet, ses textes Wikipédia et ses images."

    def add_arguments(self, parser):
        parser.add_argument("--hors-ligne", action="store_true")
        parser.add_argument("--limite", type=int, default=None)
        parser.add_argument("--refaire", action="store_true")

    def handle(self, *args, **options):
        r = catalogue.mettre_a_jour(hors_ligne=options["hors_ligne"], limite=options["limite"],
                                    refaire=options["refaire"], journal=self.stdout.write)
        if r.get("reseau"):
            self.stdout.write(f"Internet : {r.get('textes', 0)} résumés Wikipédia, {r.get('images', 0)} images, "
                              f"{r.get('sans_article', 0)} astres sans article, {r.get('deja_a_jour', 0)} déjà à jour.")
        self.stdout.write(self.style.SUCCESS(
            f"{r['astres']} astres dans le catalogue : {r['crees']} créés, {r['mis_a_jour']} mis à jour, "
            f"{r['ignores']} ignorés (déjà une fiche écrite à la main)."
        ))

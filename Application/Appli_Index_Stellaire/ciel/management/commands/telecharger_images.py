"""Partie 10 : télécharge les images des fiches dans contenu/images/ (à lancer chez toi, avec internet).

    python manage.py telecharger_images
    python manage.py telecharger_images --refaire      # retélécharge même les images déjà là

La liste est dans contenu/images_sources.json : pour chaque fichier, l'adresse de l'image et la page
où son crédit et sa licence ont été vérifiés (recopiés dans la fiche de l'astre).

Chaque image est réduite à 1200 px au plus de côté et enregistrée en JPEG (qualité 85) : quelques
centaines de Ko, raisonnable pour Git et pour un téléphone. Une image déjà présente n'est pas
retéléchargée. Ensuite : python manage.py importer_contenu, puis git add contenu/images.
"""

import io
import json
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

TAILLE_MAXI = 1200
QUALITE = 85
OCTETS_MAXI = 60 * 1024 * 1024  # on refuse de télécharger plus de 60 Mo pour une image


def reduire(contenu):
    """Octets d'une image -> octets JPEG, 1200 px au plus de côté (Pillow, déjà requis par Django)."""
    from PIL import Image

    with Image.open(io.BytesIO(contenu)) as image:
        image.load()
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((TAILLE_MAXI, TAILLE_MAXI))
        sortie = io.BytesIO()
        image.save(sortie, "JPEG", quality=QUALITE, optimize=True)
        return sortie.getvalue()


def telecharger(url):
    requete = urllib.request.Request(url, headers={"User-Agent": "Index-Stellaire (projet etudiant)"})
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        contenu = reponse.read(OCTETS_MAXI + 1)
    if len(contenu) > OCTETS_MAXI:
        raise ValueError("image trop lourde")
    return contenu


class Command(BaseCommand):
    help = "Télécharge et réduit les images listées dans contenu/images_sources.json."

    def add_arguments(self, parser):
        parser.add_argument("--dossier", default=str(Path(settings.BASE_DIR) / "contenu"))
        parser.add_argument("--refaire", action="store_true", help="retélécharger les images déjà présentes")

    def handle(self, *args, **options):
        dossier = Path(options["dossier"])
        try:
            liste = json.loads((dossier / "images_sources.json").read_text(encoding="utf-8"))["images"]
        except (OSError, ValueError, KeyError) as erreur:
            raise CommandError(f"contenu/images_sources.json illisible : {erreur}")
        (dossier / "images").mkdir(exist_ok=True)
        echecs = 0
        for nom, infos in sorted(liste.items()):
            cible = dossier / "images" / nom
            if cible.is_file() and not options["refaire"]:
                self.stdout.write(f"  déjà là : {nom}")
                continue
            try:
                octets = reduire(telecharger(infos["url"]))
            except Exception as erreur:  # noqa: BLE001 — on continue avec les autres images
                echecs += 1
                self.stdout.write(self.style.ERROR(f"  échec : {nom} ({type(erreur).__name__} : {erreur})"))
                self.stdout.write(f"    page de l'image : {infos.get('page', '?')}")
                continue
            cible.write_bytes(octets)
            self.stdout.write(self.style.SUCCESS(f"  ok : {nom} ({len(octets) // 1024} Ko)"))
        if echecs:
            raise CommandError(
                f"{echecs} image(s) non téléchargée(s). Les fiches qui les utilisent bloqueront importer_contenu : "
                "relance plus tard, ou envoie la sortie à Claude."
            )
        self.stdout.write(self.style.SUCCESS("Toutes les images sont là. Ensuite : python manage.py importer_contenu"))

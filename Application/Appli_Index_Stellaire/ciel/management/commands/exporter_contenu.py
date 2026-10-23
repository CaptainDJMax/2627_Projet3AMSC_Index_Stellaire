"""Exporte les astres de la base vers le dossier contenu/ : un fichier JSON par astre.

    python manage.py exporter_contenu
    python manage.py exporter_contenu --dossier chemin/vers/contenu

À utiliser après avoir saisi ou modifié des astres dans l'administration, avant « git add contenu ».

- Un astre déjà présent dans contenu/ (même nom) garde son fichier ; sinon, un fichier est créé,
  nommé d'après l'astre (Vénus -> venus.json, image venus.jpg).
- Un fichier n'est réécrit que s'il change : exporter sans rien modifier ne touche à rien, donc
  Git ne voit aucun changement (et pas de conflit inutile avec le travail de l'autre).
- Rien n'est supprimé dans contenu/.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from ciel.models import ObjetCeleste

from .importer_contenu import dossier_par_defaut


def texte_json(donnees):
    """Toujours la même mise en forme : un fichier identique d'un export à l'autre."""
    return json.dumps(donnees, ensure_ascii=False, indent=2) + "\n"


class Command(BaseCommand):
    help = "Exporte les astres de la base vers le dossier contenu/ (un fichier JSON par astre)."

    def add_arguments(self, parser):
        parser.add_argument("--dossier", default=str(dossier_par_defaut()), help="dossier contenu/ à écrire")

    def handle(self, *args, **options):
        dossier = Path(options["dossier"])
        (dossier / "astres").mkdir(parents=True, exist_ok=True)
        (dossier / "images").mkdir(parents=True, exist_ok=True)
        fichiers_existants = self._fichiers_par_nom(dossier)

        ecrits = 0
        for objet in ObjetCeleste.objects.order_by("nom"):
            chemin = fichiers_existants.get(objet.nom) or dossier / "astres" / f"{slugify(objet.nom) or objet.pk}.json"
            image = self._exporter_image(objet, chemin.stem, dossier)
            donnees = {
                "nom": objet.nom,
                "categorie": objet.categorie,
                "identifiant_skyfield": objet.identifiant_skyfield,
                "description": objet.description,
                "sources": [s for s in objet.sources.splitlines() if s.strip()],
                "image": image,
                "image_source": objet.image_source,
                "image_auteur": objet.image_auteur,
                "image_licence": objet.image_licence,
                "constellations": sorted(c.nom for c in objet.constellations.all()),
            }
            if image and not (objet.image_source and objet.image_auteur and objet.image_licence):
                self.stdout.write(self.style.WARNING(
                    f"  {objet.nom} : image sans crédit complet (source, auteur, licence) ; "
                    "l'import la refusera tant que ce n'est pas rempli"
                ))
            texte = texte_json(donnees)
            if not chemin.is_file() or chemin.read_text(encoding="utf-8") != texte:
                chemin.write_text(texte, encoding="utf-8")
                ecrits += 1
                self.stdout.write(f"  écrit : {chemin.name}")
        self.stdout.write(self.style.SUCCESS(f"{ecrits} fichier(s) écrit(s) dans {dossier}."))

    def _fichiers_par_nom(self, dossier):
        """Les fichiers déjà présents, par nom d'astre (pour ne jamais créer de doublon)."""
        resultat = {}
        for chemin in (dossier / "astres").glob("*.json"):
            try:
                nom = json.loads(chemin.read_text(encoding="utf-8")).get("nom")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                continue
            if isinstance(nom, str):
                resultat[nom.strip()] = chemin
        return resultat

    def _exporter_image(self, objet, base, dossier):
        """Copie l'image de l'astre dans contenu/images/, nommée comme son fichier. Renvoie le nom."""
        if not objet.image:
            return ""
        source = Path(objet.image.path)
        if not source.is_file():
            self.stdout.write(self.style.WARNING(f"  {objet.nom} : image introuvable ({source}), ignorée"))
            return ""
        nom = base + source.suffix.lower()
        destination = dossier / "images" / nom
        contenu = source.read_bytes()
        if not destination.is_file() or destination.read_bytes() != contenu:
            destination.write_bytes(contenu)
            self.stdout.write(f"  image : {nom}")
        return nom
